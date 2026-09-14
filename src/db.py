"""
Database layer for IndianLawGPT.

SQLite by default (zero external services). The `documents` table is
source-agnostic: a row can be a scraped case judgment, a PDF-derived
document, a statute section, or a commentary — `source_type` distinguishes
them and `metadata_json` carries type-specific extras (act/section details
for statutes, total_pages for PDFs) without further schema churn.

To move to PostgreSQL later (for real tsvector full-text search and
concurrent access), change SQLITE_DB_PATH usage below to a real connection
and swap the FTS query in search_keyword() for a tsvector query.
"""
import json
import os
import re
import sqlite3
from typing import Dict, Iterable, List, Optional

from config import settings
from logging_config import get_logger

logger = get_logger("db")

DB_PATH = settings.sqlite_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'case_law',  -- 'case_law' | 'pdf' | 'statute' | 'commentary'
    court TEXT,
    date TEXT,
    judges TEXT,           -- comma-separated for simplicity
    file_name TEXT,        -- original source file, if any (JSON or PDF)
    full_text TEXT NOT NULL,
    metadata_json TEXT,    -- free-form extra metadata, JSON-encoded
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- SQLite full-text search virtual table (stands in for Postgres tsvector)
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    doc_id UNINDEXED,
    title,
    full_text,
    content='documents',
    content_rowid='rowid'
);

CREATE TABLE IF NOT EXISTS citations (
    citing_doc_id TEXT NOT NULL,
    cited_doc_id TEXT NOT NULL,
    FOREIGN KEY (citing_doc_id) REFERENCES documents(doc_id),
    FOREIGN KEY (cited_doc_id) REFERENCES documents(doc_id)
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT,
    answer TEXT,
    rating TEXT,           -- 'up' or 'down'
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    # timeout: how long a call waits for a lock before raising "database is locked",
    # instead of the 5s default — matters because callers like get_document() open a
    # fresh connection while a long-running ingestion script holds a write transaction
    # open across many inserts (committed only periodically).
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    # WAL: readers don't block on a writer's uncommitted transaction (the default
    # rollback-journal mode locks the whole DB against readers while a write is open).
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        logger.info("Database initialized at %s", DB_PATH)
    except sqlite3.Error:
        logger.exception("Failed to initialize database at %s", DB_PATH)
        raise
    finally:
        conn.close()


def upsert_document(
    conn: sqlite3.Connection,
    doc_id: str,
    title: str,
    full_text: str,
    source_type: str = "case_law",
    court: str = "",
    date: str = "",
    judges: str = "",
    file_name: str = "",
    metadata: dict = None,
):
    """Shared insert/replace used by the JSON case-law, PDF and statute ingesters."""
    metadata_json = json.dumps(metadata or {})
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO documents
                (doc_id, title, source_type, court, date, judges, file_name, full_text, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, title, source_type, court, date, judges, file_name, full_text, metadata_json),
        )
        conn.execute(
            "INSERT OR REPLACE INTO documents_fts (doc_id, title, full_text) VALUES (?, ?, ?)",
            (doc_id, title, full_text),
        )
    except sqlite3.Error:
        logger.exception("Failed to upsert document doc_id=%s", doc_id)
        raise


def document_exists(doc_id: str) -> bool:
    """Core function used by the citation verifier — does this doc ID actually exist?"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT 1 FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        return row is not None
    except sqlite3.Error:
        logger.exception("document_exists() query failed for doc_id=%s", doc_id)
        return False
    finally:
        conn.close()


def get_document(doc_id: str):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        logger.exception("get_document() query failed for doc_id=%s", doc_id)
        return None
    finally:
        conn.close()


def get_documents_brief(doc_ids: Iterable[str], include_text: bool = False) -> List[Dict]:
    """Batch lookup for enriching many retrieved/cited documents in one query."""
    ids = [d for d in dict.fromkeys(doc_ids) if d]
    if not ids:
        return []
    columns = "doc_id, title, source_type, court, date, judges, file_name, metadata_json"
    if include_text:
        columns += ", full_text"
    placeholders = ",".join("?" for _ in ids)
    conn = get_connection()
    try:
        rows = conn.execute(f"SELECT {columns} FROM documents WHERE doc_id IN ({placeholders})", ids).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        logger.exception("get_documents_brief() failed for %d id(s)", len(ids))
        return []
    finally:
        conn.close()


def _build_fts_query(raw_query: str) -> str:
    """FTS5 MATCH syntax treats characters like ? " ( ) - * : as operators, so passing a raw
    natural-language question straight through (e.g. one ending in '?') reliably raises an
    OperationalError and silently kills every keyword hit. Tokenize to plain words and quote
    each as a literal phrase (stripping the FTS5-operator meaning), OR'd together so any
    matching term counts as a keyword hit."""
    tokens = re.findall(r"[A-Za-z0-9]+", raw_query)
    terms = [t for t in tokens if len(t) > 2]
    if not terms:
        return ""
    escaped = [f'"{t}"' for t in terms]
    return " OR ".join(escaped)


def search_keyword(query: str, limit: int = 5, source_type: Optional[str] = None):
    """Keyword half of hybrid search, using SQLite FTS5 (Postgres tsvector equivalent).
    Ranked by BM25: with an OR query over tens of thousands of documents almost every
    row matches, so an unordered LIMIT would return whichever rows have the lowest
    rowid rather than the strongest matches."""
    fts_query = _build_fts_query(query)
    if not fts_query:
        return []

    sql = """
        SELECT documents.doc_id, documents.title, documents.court, documents.date, documents.source_type
        FROM documents_fts
        JOIN documents ON documents.doc_id = documents_fts.doc_id
        WHERE documents_fts MATCH ?
    """
    params: list = [fts_query]
    if source_type:
        sql += " AND documents.source_type = ?"
        params.append(source_type)
    sql += " ORDER BY bm25(documents_fts) LIMIT ?"
    params.append(limit)

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [
            {
                "doc_id": r["doc_id"], "title": r["title"], "court": r["court"],
                "date": r["date"], "source_type": r["source_type"],
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        logger.warning("FTS5 query failed for query=%r; returning no keyword hits", query, exc_info=True)
        return []
    except sqlite3.Error:
        logger.exception("search_keyword() failed for query=%r", query)
        return []
    finally:
        conn.close()


def get_corpus_stats() -> Dict:
    conn = get_connection()
    try:
        by_type = {
            r["source_type"]: r["n"]
            for r in conn.execute("SELECT source_type, COUNT(*) AS n FROM documents GROUP BY source_type")
        }
        acts = conn.execute(
            "SELECT COUNT(DISTINCT json_extract(metadata_json, '$.act_id')) FROM documents WHERE source_type = 'statute'"
        ).fetchone()[0]
        return {"documents": sum(by_type.values()), "by_source_type": by_type, "acts": acts}
    finally:
        conn.close()


def _section_sort_key(section_number) -> tuple:
    match = re.match(r"(\d+)\s*([A-Za-z]*)", str(section_number or ""))
    if match:
        return (int(match.group(1)), match.group(2).upper())
    return (float("inf"), str(section_number))


def list_act_sections(act_id: str) -> Optional[Dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT doc_id,
                   json_extract(metadata_json, '$.act_title') AS act_title,
                   json_extract(metadata_json, '$.section_number') AS section_number,
                   json_extract(metadata_json, '$.section_heading') AS section_heading
            FROM documents
            WHERE source_type = 'statute' AND json_extract(metadata_json, '$.act_id') = ?
            """,
            (act_id,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None
    sections = sorted(
        ({"doc_id": r["doc_id"], "section_number": r["section_number"], "section_heading": r["section_heading"]}
         for r in rows),
        key=lambda s: _section_sort_key(s["section_number"]),
    )
    return {"act_id": act_id, "act_title": rows[0]["act_title"], "sections": sections}


def list_mapped_acts() -> List[Dict]:
    """Acts whose sections carry published old↔new code correspondences."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT json_extract(metadata_json, '$.act_id') AS act_id,
                   MAX(json_extract(metadata_json, '$.act_title')) AS act_title,
                   MAX(json_extract(metadata_json, '$.corresponds_to[0].act')) AS counterpart_act_id,
                   MAX(json_extract(metadata_json, '$.corresponds_to[0].direction')) AS direction,
                   COUNT(*) AS mapped_sections
            FROM documents
            WHERE source_type = 'statute' AND json_array_length(metadata_json, '$.corresponds_to') > 0
            GROUP BY act_id
            ORDER BY act_title
            """
        ).fetchall()
    finally:
        conn.close()
    acts = [dict(r) for r in rows]
    titles = {a["act_id"]: a["act_title"] for a in acts}
    for act in acts:
        act["counterpart_act_title"] = titles.get(act["counterpart_act_id"])
    return acts


# --- Backwards-compatible aliases (legacy call sites still reference these names) ---
case_exists = document_exists
get_case = get_document
