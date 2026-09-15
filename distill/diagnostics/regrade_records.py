"""
Re-applies the current deterministic quality gates to stored teacher records without calling Claude:
required-source coverage is recomputed from each record's own citations and retrieved context, principle
equivalents are re-confirmed from the stored grader verdict, and grade() is re-run. Answers, citations,
retrieval and grader verdicts are untouched. The previous file is kept as teacher_records.before_regrade.jsonl.

Usage (from the repository root):
    .venv/bin/python distill/diagnostics/regrade_records.py --run pilot_v2
"""
import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "distill"))

from common import latest_by_id, read_jsonl, write_jsonl  # noqa: E402
from generate_teacher import confirm_principle_equivalents, grade, quote_supported_ids, seed_coverage  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    run = ROOT / "data" / "distill" / args.run
    questions = {q["id"]: q for q in read_jsonl(run / "questions.jsonl")}
    path = run / "teacher_records.jsonl"
    records = list(latest_by_id(read_jsonl(path)).values())
    shutil.copy(path, run / "teacher_records.before_regrade.jsonl")

    changes = Counter()
    updated = []
    for record in records:
        question = questions[record["id"]]
        retrieved = record["retrieved_context"]
        retrieved_ids = {d["doc_id"] for d in retrieved}
        cited_ids = {c["doc_id"] for c in record["citations"]} | quote_supported_ids(record["citations"], retrieved)
        checks = {**record["checks"], **seed_coverage(question, retrieved_ids, cited_ids)}
        if not (record.get("grader") or {}).get("error"):
            confirm_principle_equivalents(checks, retrieved, record["grader"])
        status, reasons, answer_type, classification = grade(question, checks, record["grader"])
        if status != record["quality_status"] or reasons != record["status_reasons"]:
            changes[(record["quality_status"], status)] += 1
            print(f"{record['id']} {record['category']:22} {record['quality_status']} -> {status}  {record['status_reasons']} -> {reasons}")
        record.update({
            "checks": checks, "quality_status": status, "status": status.lower(), "status_reasons": reasons,
            "answer_type": answer_type, "insufficiency_classification": classification,
            "required_sources": checks["required_sources"], "retrieved_all_required_sources": checks["seed_all_retrieved"],
            "missing_required_sources": [r["source_doc_id"] for r in checks["required_sources"] if not r["satisfied_by"]],
            "refusal_training_eligible": status == "VERIFIED" and classification == "TRUE_INSUFFICIENT" and answer_type == "insufficient_evidence",
        })
        updated.append(record)
    write_jsonl(path, updated)
    print("status changes:", dict(changes))


if __name__ == "__main__":
    main()
