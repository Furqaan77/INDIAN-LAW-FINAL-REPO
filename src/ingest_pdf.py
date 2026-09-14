"""
PDF ingestion pipeline:
    PDF -> extract (pdf_extract) -> clean (text_cleaning) -> legal chunking
    (legal_chunker) -> metadata -> OpenAI embeddings -> vector DB (vector_store)
plus a SQLite `documents` row (source_type='pdf') so every chunk is traceable
back to its file, and so PDFs participate in keyword search and citation
verification alongside case-law judgments.

Usage:
    python ingest_pdf.py --input ../data/pdfs/
    python ingest_pdf.py --input ../data/pdfs/ --force   # re-ingest unchanged files too

Designed to be run repeatedly as more PDFs are added: each file gets a
stable doc_id derived from its path (relative to --input, so subfolders are
supported), and unchanged files (by content hash) are skipped on subsequent
runs unless --force is passed. A changed file gets its old chunks replaced,
not duplicated.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Dict, List

from config import settings
from db import get_connection, get_document, init_db, upsert_document
from legal_chunker import chunk_pdf_text
from logging_config import get_logger
from pdf_extract import extract_pdf_pages
from text_cleaning import clean_pdf_pages
from vector_store import get_vector_store

logger = get_logger("ingest_pdf")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return slug[:80] or "document"


def _make_doc_id(relative_path: str) -> str:
    stem = os.path.splitext(relative_path)[0]
    return f"PDF-{_slugify(stem)}"


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _build_full_text_and_page_map(pages: List[Dict]):
    """Concatenate cleaned pages, returning full text plus a list of
    (start_offset, end_offset, page_number) used to map chunk offsets back
    to the source page(s)."""
    parts = []
    page_map = []
    offset = 0
    for p in pages:
        text = p["text"]
        start = offset
        parts.append(text)
        offset += len(text)
        page_map.append((start, offset, p["page_number"]))
        parts.append("\n\n")
        offset += 2
    return "".join(parts), page_map


def _pages_for_range(page_map, start: int, end: int):
    covered = [pn for (s, e, pn) in page_map if e > start and s < end]
    if not covered:
        covered = [page_map[-1][2]] if page_map else [1]
    return min(covered), max(covered)


def ingest_pdf_file(conn, path: str, base_dir: str, force: bool = False) -> bool:
    rel_path = os.path.relpath(path, base_dir).replace(os.sep, "/")
    doc_id = _make_doc_id(rel_path)
    content_hash = _file_hash(path)

    existing = get_document(doc_id)
    if existing and not force:
        try:
            existing_meta = json.loads(existing.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            existing_meta = {}
        if existing_meta.get("content_hash") == content_hash:
            logger.info("Skipping unchanged PDF: %s (doc_id=%s)", rel_path, doc_id)
            return False

    logger.info("Ingesting PDF: %s (doc_id=%s)", rel_path, doc_id)
    try:
        raw_pages = extract_pdf_pages(path)
    except Exception:
        logger.error("Extraction failed for %s — skipping this file", rel_path, exc_info=True)
        return False

    cleaned_pages = clean_pdf_pages(raw_pages)
    full_text, page_map = _build_full_text_and_page_map(cleaned_pages)

    if not full_text.strip():
        logger.warning("No extractable text in %s — skipping (may need OCR)", rel_path)
        return False

    title = Path(path).stem.replace("_", " ").replace("-", " ").strip()

    sections = chunk_pdf_text(full_text, settings.chunk_target_chars, settings.chunk_overlap_chars)
    if not sections:
        logger.warning("Chunking produced no chunks for %s — skipping", rel_path)
        return False

    upsert_document(
        conn, doc_id=doc_id, title=title, full_text=full_text, source_type="pdf",
        file_name=rel_path,
        metadata={"content_hash": content_hash, "total_pages": len(cleaned_pages), "num_chunks": len(sections)},
    )
    conn.commit()

    ids, documents, metadatas = [], [], []
    for i, (label, chunk_text, start, end) in enumerate(sections):
        if not chunk_text.strip():
            continue
        page_start, page_end = _pages_for_range(page_map, start, end)
        chunk_id = f"{doc_id}_chunk{i}"
        ids.append(chunk_id)
        documents.append(chunk_text)
        metadatas.append({
            "doc_id": doc_id, "title": title, "source_type": "pdf",
            "court": "", "date": "", "file_name": rel_path,
            "section": label or "general", "page_start": page_start, "page_end": page_end,
            "chunk_id": chunk_id,
        })

    store = get_vector_store()
    if existing:
        store.delete_by_doc_id(doc_id)  # avoid orphaned/duplicate chunks from a previous version of this file
    store.upsert(ids, documents, metadatas)

    logger.info("Indexed %d chunks from %s", len(ids), rel_path)
    return True


def build_index(input_dir: str, force: bool = False):
    init_db()
    conn = get_connection()

    pdf_paths = sorted(str(p) for p in Path(input_dir).rglob("*.pdf"))
    logger.info("Found %d PDF file(s) under %s", len(pdf_paths), input_dir)

    ingested = 0
    for path in pdf_paths:
        try:
            if ingest_pdf_file(conn, path, input_dir, force=force):
                ingested += 1
        except Exception:
            logger.error("Unexpected failure ingesting %s — continuing with next file", path, exc_info=True)

    conn.close()
    logger.info(
        "PDF ingestion complete: %d/%d file(s) newly ingested (rest unchanged/skipped)",
        ingested, len(pdf_paths),
    )


def main():
    parser = argparse.ArgumentParser(description="Ingest PDFs into SQLite + vector store.")
    parser.add_argument("--input", required=True, help="Directory containing PDFs (searched recursively).")
    parser.add_argument("--force", action="store_true", help="Re-ingest even unchanged files.")
    args = parser.parse_args()
    build_index(args.input, force=args.force)


if __name__ == "__main__":
    main()
