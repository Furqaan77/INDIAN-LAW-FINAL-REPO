"""
Prints a compact, human-readable review sheet for a teacher run: question, category, required sources and
whether each was retrieved, retrieved evidence, quality status and reasons, grader notes and the answer.

Usage (from the repository root):
    .venv/bin/python distill/diagnostics/review_dump.py --run pilot_v2 > review.txt
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    path = ROOT / "data" / "distill" / args.run / "teacher_records.jsonl"
    records = {}
    for line in path.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            records[record["id"]] = record
    for record in sorted(records.values(), key=lambda r: (r["category"], r["id"])):
        print("=" * 100)
        print(f"{record['id']} | {record['category']} | {record.get('case_law_type') or ''} | {record['quality_status']} | "
              f"{record['answer_type']} | {record.get('insufficiency_classification')} | {record['status_reasons']}")
        print("Q:", record["question"])
        for source in record["required_sources"]:
            print(f"  required {source['kind']}/{source['equivalence']} {source['source_doc_id']} "
                  f"accepted={source['accepted_doc_count']} satisfied_by={source.get('satisfied_by')} retrieved={source['retrieved_doc_ids'][:3]}")
        print("  retrieved:", [(c["doc_id"], c.get("required_reason"), c.get("context_span")) for c in record["retrieved_context"]])
        grader = record.get("grader") or {}
        print("  grader:", {k: grader.get(k) for k in ("supported", "invented_authority", "answers_question", "answer_type",
                                                       "insufficiency_justified", "concise", "error")})
        print("  grader notes:", (grader.get("notes") or "")[:500])
        print(f"  verified citations: {record['verified_citations']} | chars={record['checks']['answer_chars']}")
        print("ANSWER:\n" + record["teacher_answer"])


if __name__ == "__main__":
    main()
