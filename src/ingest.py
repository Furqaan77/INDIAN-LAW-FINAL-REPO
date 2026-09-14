"""
Ingest case-law judgment JSON files into the database.
Usage: python ingest.py --input ../data/sample_judgments/
"""
import argparse
import json
import os

from db import get_connection, init_db, upsert_document
from logging_config import get_logger

logger = get_logger("ingest")


def ingest_file(conn, filepath) -> bool:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    required = ["case_id", "title", "full_text"]
    missing = [k for k in required if k not in data]
    if missing:
        logger.warning("Skipping %s: missing fields %s", filepath, missing)
        return False

    judges = ", ".join(data.get("judges", []))
    upsert_document(
        conn,
        doc_id=data["case_id"],
        title=data["title"],
        full_text=data["full_text"],
        source_type="case_law",
        court=data.get("court", ""),
        date=data.get("date", ""),
        judges=judges,
        file_name=os.path.basename(filepath),
    )
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    init_db()
    conn = get_connection()

    files = [f for f in os.listdir(args.input) if f.endswith(".json")]
    logger.info("Found %d JSON file(s) in %s", len(files), args.input)

    ok = 0
    for fname in files:
        try:
            if ingest_file(conn, os.path.join(args.input, fname)):
                ok += 1
        except Exception:
            logger.error("Failed to ingest %s", fname, exc_info=True)
    conn.commit()
    conn.close()
    logger.info("Ingested %d/%d judgment(s).", ok, len(files))


if __name__ == "__main__":
    main()
