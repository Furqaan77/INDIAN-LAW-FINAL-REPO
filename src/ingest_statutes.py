"""
Ingest the Indian Central Acts statute corpus (a JSONL file, one record per
statutory section, with metadata: act title/year, section number/heading,
source URL, cross-code correspondences) into SQLite + vector store,
source_type='statute'.

Each record is already one statutory section — pre-segmented upstream — so
it's treated as one `documents` row, matching the natural unit lawyers cite
("Section 10 of the Indian Contract Act, 1872"). Only the minority of
unusually long sections get split further, reusing legal_chunker's
size-enforcement logic rather than duplicating it.

Chunks are buffered across many sections and flushed to the vector store in
batches (not one upsert per section) — with ~38k sections, a per-section
flush would mean tens of thousands of separate embedding calls; batching
keeps this to a few hundred.

Usage:
    python ingest_statutes.py --input ../data/statutes/indian_law_corpus.jsonl
    python ingest_statutes.py --input ../data/statutes/indian_law_corpus.jsonl --limit 200     # smoke test
    python ingest_statutes.py --input ../data/statutes/indian_law_corpus.jsonl --force          # re-embed everything
    python ingest_statutes.py --input ../data/statutes/indian_law_corpus.jsonl --metadata-only  # refresh metadata, no embeddings
"""
import argparse
import json
import re

from config import settings
from db import get_connection, get_document, init_db, upsert_document
from legal_chunker import enforce_chunk_size
from logging_config import get_logger
from vector_store import get_vector_store

logger = get_logger("ingest_statutes")

FLUSH_EVERY_N_CHUNKS = 300
METADATA_UPDATE_BATCH = 1000


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(name)).strip("-").lower()
    return slug or "0"


def make_statute_doc_id(act_id: str, section_number: str) -> str:
    return f"STATUTE-{act_id}-s{_slugify(section_number)}"


def _statute_title(meta: dict, act_id: str, section_number) -> str:
    title = meta.get("act_title") or act_id
    if section_number:
        title += f" — Section {section_number}"
    if meta.get("section_heading"):
        title += f" ({meta['section_heading']})"
    return title


def _statute_metadata(meta: dict, act_id: str, section_number) -> dict:
    return {
        "act_id": act_id, "act_title": meta.get("act_title"), "act_long_title": meta.get("act_long_title"),
        "act_number": meta.get("act_number"), "act_year": meta.get("act_year"),
        "enforcement_date": meta.get("enforcement_date"), "ministry": meta.get("ministry"),
        "section_number": section_number, "section_heading": meta.get("section_heading"),
        "source_url": meta.get("source_url"),
        # Upstream-published correspondences between old and new codes (IPC↔BNS, CrPC↔BNSS,
        # IEA↔BSA, Income-tax 1961↔2025), each with direction, relation and a match score.
        # Empty for every other act.
        "corresponds_to": meta.get("corresponds_to") or [],
    }


def _flush(store, buffer_ids, buffer_docs, buffer_metas):
    if not buffer_ids:
        return
    store.upsert(buffer_ids, buffer_docs, buffer_metas)
    buffer_ids.clear()
    buffer_docs.clear()
    buffer_metas.clear()


def ingest_statutes(input_path: str, force: bool = False, limit: int = None):
    init_db()
    conn = get_connection()
    store = get_vector_store()

    total_read = 0
    ingested = 0
    skipped_unchanged = 0
    skipped_invalid = 0
    total_chunks = 0

    buffer_ids, buffer_docs, buffer_metas = [], [], []

    with open(input_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if limit and total_read >= limit:
                break
            line = line.strip()
            if not line:
                continue
            total_read += 1

            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSONL line %d", line_num)
                skipped_invalid += 1
                continue

            text = (record.get("text") or "").strip()
            meta = record.get("metadata", {}) or {}
            act_id = meta.get("act_id")
            section_number = meta.get("section_number")
            if not text or not act_id:
                skipped_invalid += 1
                continue

            doc_id = make_statute_doc_id(act_id, section_number)

            existing = get_document(doc_id)
            if existing and not force:
                # Statute section text is static once scraped from India Code — skip re-embedding cost.
                skipped_unchanged += 1
                continue

            title = _statute_title(meta, act_id, section_number)

            upsert_document(
                conn, doc_id=doc_id, title=title, full_text=text, source_type="statute",
                court="", date=meta.get("enact_date") or "", file_name=meta.get("source_url") or "",
                metadata=_statute_metadata(meta, act_id, section_number),
            )

            sections = enforce_chunk_size(
                [(meta.get("section_heading"), text, 0, len(text))],
                settings.chunk_target_chars, settings.chunk_overlap_chars,
            )

            if existing:
                store.delete_by_doc_id(doc_id)  # re-ingesting a changed section: drop its old chunks first

            for i, (label, chunk_text, _s, _e) in enumerate(sections):
                if not chunk_text.strip():
                    continue
                chunk_id = f"{doc_id}_chunk{i}"
                buffer_ids.append(chunk_id)
                buffer_docs.append(chunk_text)
                buffer_metas.append({
                    "doc_id": doc_id, "title": title, "source_type": "statute",
                    "court": "", "date": meta.get("enact_date") or "", "file_name": meta.get("source_url") or "",
                    "section": label or (f"Section {section_number}" if section_number else "general"),
                    "page_start": 0, "page_end": 0, "chunk_id": chunk_id,
                })
                total_chunks += 1

            ingested += 1

            if len(buffer_ids) >= FLUSH_EVERY_N_CHUNKS:
                _flush(store, buffer_ids, buffer_docs, buffer_metas)

            if ingested % 1000 == 0:
                conn.commit()
                logger.info(
                    "Progress: %d ingested, %d chunks so far (%d records read)",
                    ingested, total_chunks, total_read,
                )

    _flush(store, buffer_ids, buffer_docs, buffer_metas)
    conn.commit()
    conn.close()

    logger.info(
        "Statute ingestion complete: %d ingested, %d skipped (unchanged), %d skipped (invalid), "
        "%d total chunks, out of %d records read",
        ingested, skipped_unchanged, skipped_invalid, total_chunks, total_read,
    )


def backfill_metadata(input_path: str):
    """Rewrite metadata_json for already-ingested sections without re-embedding.
    For when the stored metadata shape grows but section text (and so its
    vectors) is unchanged."""
    conn = get_connection()
    updates = []
    before = conn.total_changes

    def apply():
        conn.executemany(
            "UPDATE documents SET metadata_json = ? WHERE doc_id = ? AND source_type = 'statute'", updates,
        )
        conn.commit()
        updates.clear()

    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            meta = record.get("metadata", {}) or {}
            act_id = meta.get("act_id")
            if not act_id:
                continue
            section_number = meta.get("section_number")
            updates.append((
                json.dumps(_statute_metadata(meta, act_id, section_number)),
                make_statute_doc_id(act_id, section_number),
            ))
            if len(updates) >= METADATA_UPDATE_BATCH:
                apply()

    if updates:
        apply()
    updated = conn.total_changes - before
    conn.close()
    logger.info("Metadata backfill complete: %d statute section(s) updated", updated)


def main():
    parser = argparse.ArgumentParser(description="Ingest the Indian Central Acts statute corpus JSONL.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--force", action="store_true", help="Re-ingest and re-embed even unchanged sections.")
    parser.add_argument("--limit", type=int, default=None, help="Only ingest the first N records (for testing).")
    parser.add_argument("--metadata-only", action="store_true",
                        help="Only refresh stored metadata for already-ingested sections; no embedding calls.")
    args = parser.parse_args()
    if args.metadata_only:
        backfill_metadata(args.input)
    else:
        ingest_statutes(args.input, force=args.force, limit=args.limit)


if __name__ == "__main__":
    main()
