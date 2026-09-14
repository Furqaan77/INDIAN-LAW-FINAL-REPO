"""
Build/refresh the vector index for case-law judgments already ingested into
SQLite by ingest.py (source_type='case_law'). Run after ingest.py:
    python chunk_embed.py

Shares one Chroma collection with PDF ingestion (ingest_pdf.py). Chunks are
deleted and re-added per document (not a full collection rebuild), so this
is safe to re-run without touching PDF-sourced chunks, and produces the same
metadata shape (doc_id, title, source_type, court, date, file_name, section,
page_start, page_end, chunk_id) that search.py and rag_chain.py expect
regardless of whether a chunk came from a case or a PDF.
"""
from config import settings
from db import get_connection
from legal_chunker import chunk_case_law_text
from logging_config import get_logger
from vector_store import get_vector_store

logger = get_logger("chunk_embed")


def build_index(source_type: str = "case_law"):
    conn = get_connection()
    cases = conn.execute(
        "SELECT doc_id, title, court, date, full_text FROM documents WHERE source_type = ?",
        (source_type,),
    ).fetchall()
    conn.close()

    if not cases:
        logger.warning("No documents with source_type='%s' found. Run ingest.py first.", source_type)
        return

    store = get_vector_store()
    total_chunks = 0

    for case in cases:
        sections = chunk_case_law_text(
            case["full_text"], settings.chunk_target_chars, settings.chunk_overlap_chars
        )

        ids, documents, metadatas = [], [], []
        for i, (label, chunk_text, _start, _end) in enumerate(sections):
            if not chunk_text.strip():
                continue
            chunk_id = f"{case['doc_id']}_chunk{i}"
            ids.append(chunk_id)
            documents.append(chunk_text)
            metadatas.append({
                "doc_id": case["doc_id"], "title": case["title"], "source_type": source_type,
                "court": case["court"] or "", "date": case["date"] or "", "file_name": "",
                "section": label or "general", "page_start": 0, "page_end": 0,
                "chunk_id": chunk_id,
            })

        if not ids:
            continue

        store.delete_by_doc_id(case["doc_id"])
        store.upsert(ids, documents, metadatas)
        total_chunks += len(ids)
        logger.info("Indexed %d chunk(s) for %s", len(ids), case["doc_id"])

    logger.info("Done: indexed %d total chunks from %d case(s) into the vector store.", total_chunks, len(cases))


if __name__ == "__main__":
    build_index()
