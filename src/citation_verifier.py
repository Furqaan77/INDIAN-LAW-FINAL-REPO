"""
Citation Verifier — the most important file in this repo.
Extracts every [SOURCE: doc_id] the Python layer injected (never trusting
the LLM's own claimed IDs — see rag_chain.py), checks each one against the
database, and never presents an unverified citation as fact.
"""
import re

import instrumentation
from db import document_exists, get_document
from logging_config import get_logger

logger = get_logger("citation_verifier")

CITATION_PATTERN = re.compile(r"\[SOURCE:\s*([A-Za-z0-9_\-\.]+)\]")


def extract_citations(answer_text: str):
    instrumentation.log("13", "Citation extraction START")
    instrumentation.start("Citation extraction")
    matches = CITATION_PATTERN.findall(answer_text or "")
    seen = set()
    ordered = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            ordered.append(m)
    dur = instrumentation.end("Citation extraction")
    instrumentation.log("13", f"Citation extraction END: {dur:.3f} sec")
    instrumentation.log("13", f"Citations extracted: {len(ordered)}")
    return ordered


def verify_citations(answer_text: str, validated_ids: set = None):
    instrumentation.log("14", "Citation verification START")
    instrumentation.start("Citation verification")
    claimed = extract_citations(answer_text)
    verified = []
    unverified = []
    clean_answer = answer_text

    for doc_id in claimed:
        is_valid = document_exists(doc_id)
        if is_valid and validated_ids is not None and doc_id not in validated_ids:
            # Exists in the DB, but wasn't the doc_id the deterministic quote-match
            # actually resolved to — treat as unverified rather than trust the LLM.
            is_valid = False

        if is_valid:
            doc = get_document(doc_id)
            verified.append({
                "doc_id": doc_id, "title": doc["title"],
                "court": doc.get("court"), "date": doc.get("date"),
                "source_type": doc.get("source_type"), "file_name": doc.get("file_name"),
            })
        else:
            unverified.append(doc_id)
            logger.info("Unverified citation encountered: %s", doc_id)

    dur = instrumentation.end("Citation verification")
    instrumentation.log("14", f"Citation verification END: {dur:.3f} sec")
    instrumentation.log("14", f"Verified citations: {len(verified)}")
    instrumentation.log("14", f"Unverified citations: {len(unverified)}")

    return {
        "verified": verified,
        "unverified": unverified,
        "clean_answer": clean_answer,
        "accuracy_note": (
            f"{len(verified)}/{len(claimed)} citations verified and grounded" if claimed else "No citations were made"
        ),
    }
