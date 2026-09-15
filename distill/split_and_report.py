"""
Stage 3 — clean dataset, leakage-safe split, and run report.

Only examples with quality_status VERIFIED enter train / validation / test. NEEDS_REVIEW and REJECTED
examples are written to needs_review.jsonl and rejected.jsonl for analysis, never discarded.

Split without leakage: examples are grouped before splitting. Two examples share a group when they
share any seed source document (the same section, pair of sections or judgment) or when their questions
are near-duplicates (token Jaccard >= 0.5). Groups are ordered by a hash salted with the fixed seed and
assigned to test, then validation, until each holds ~10% of the clean examples; the rest go to train.
The report verifies that no source document and no near-duplicate question crosses split boundaries.

Writes train.jsonl / validation.jsonl / test.jsonl, needs_review.jsonl, rejected.jsonl, report.json and
report.md.

Usage (from the repository root):
    .venv/bin/python distill/split_and_report.py --run pilot_v2
"""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean, median

from common import SEED, get_logger, jaccard, latest_by_id, question_tokens, read_jsonl, run_dir, write_jsonl

logger = get_logger("distill.split")

TRAINING_FIELDS = [
    "id", "question", "category", "case_law_type", "expected", "answer_type", "insufficiency_classification",
    "refusal_training_eligible", "intended_source_ids", "required_sources", "retrieved_source_ids",
    "retrieved_all_required_sources", "retrieval_trace", "retrieved_context", "teacher_prompt", "teacher_answer",
    "citations", "verified_citations", "source_ids", "target", "quality_status", "seed", "teacher", "created_at",
]
NEAR_DUPLICATE = 0.5
LONG_ANSWER_CHARS = 1200


def status_of(record):
    return record.get("quality_status") or record.get("status", "").upper()


def rate(numerator, denominator):
    return round(numerator / denominator, 3) if denominator else None


class Groups:
    def __init__(self, items):
        self.parent = {item: item for item in items}

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a, b):
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[max(root_a, root_b)] = min(root_a, root_b)


def assign_splits(records):
    ids = [r["id"] for r in records]
    groups = Groups(ids)
    by_doc = defaultdict(list)
    for record in records:
        for doc_id in record["seed"].get("doc_ids") or []:
            by_doc[doc_id].append(record["id"])
    for members in by_doc.values():
        for other in members[1:]:
            groups.union(members[0], other)
    tokens = {r["id"]: question_tokens(r["question"]) for r in records}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if jaccard(tokens[a], tokens[b]) >= NEAR_DUPLICATE:
                groups.union(a, b)

    members = defaultdict(list)
    for record_id in ids:
        members[groups.find(record_id)].append(record_id)
    ordered = sorted(members.values(), key=lambda m: hashlib.sha256(f"{SEED}:{min(m)}".encode("utf-8")).hexdigest())
    target = {"test": round(0.1 * len(ids)), "validation": round(0.1 * len(ids))}
    split_of, counts = {}, Counter()
    for group in ordered:
        name = next((s for s in ("test", "validation") if counts[s] + len(group) <= target[s] or counts[s] == 0 and target[s]), "train")
        if name != "train" and counts[name] >= target[name]:
            name = "train"
        for record_id in group:
            split_of[record_id] = name
        counts[name] += len(group)
    return split_of, {"groups": len(members), "largest_group": max((len(m) for m in members.values()), default=0)}


def leakage(records, split_of):
    doc_splits = defaultdict(set)
    for record in records:
        for doc_id in record["seed"].get("doc_ids") or []:
            doc_splits[doc_id].add(split_of[record["id"]])
    tokens = {r["id"]: question_tokens(r["question"]) for r in records}
    near = 0
    for i, a in enumerate(records):
        for b in records[i + 1:]:
            if split_of[a["id"]] != split_of[b["id"]] and jaccard(tokens[a["id"]], tokens[b["id"]]) >= NEAR_DUPLICATE:
                near += 1
    return {"source_documents_in_multiple_splits": sum(1 for s in doc_splits.values() if len(s) > 1),
            "near_duplicate_pairs_across_splits": near}


def act_of(record):
    for source in record.get("required_sources") or []:
        doc_id = source.get("source_doc_id") or ""
        if doc_id.startswith("STATUTE-"):
            context = next((c for c in record.get("retrieved_context") or [] if c["doc_id"] == doc_id), None)
            if context and context.get("act_title"):
                return context["act_title"]
    labels = record["seed"].get("labels") or []
    return labels[0].split(" - Section")[0] if labels and " - Section" in labels[0] else ("Judgment" if labels else "unknown")


def main():
    parser = argparse.ArgumentParser(description="Split verified teacher examples and report on the run.")
    parser.add_argument("--run", required=True)
    args = parser.parse_args()

    run = run_dir(args.run)
    questions = read_jsonl(run / "questions.jsonl")
    attempts = read_jsonl(run / "question_attempts.jsonl")
    records = list(latest_by_id(read_jsonl(run / "teacher_records.jsonl")).values())
    failures = read_jsonl(run / "failures.jsonl")
    if not records:
        raise SystemExit("No teacher records yet - run generate_teacher.py first.")

    by_status = defaultdict(list)
    for record in records:
        by_status[status_of(record)].append(record)
    clean = sorted(by_status["VERIFIED"], key=lambda r: r["id"])
    split_of, group_info = assign_splits(clean)
    splits = defaultdict(list)
    for record in clean:
        splits[split_of[record["id"]]].append({field: record.get(field) for field in TRAINING_FIELDS})
    for name in ("train", "validation", "test"):
        write_jsonl(run / f"{name}.jsonl", splits[name])
    write_jsonl(run / "needs_review.jsonl", by_status["NEEDS_REVIEW"])
    write_jsonl(run / "rejected.jsonl", by_status["REJECTED"])

    usable = [r for r in records if not r["checks"]["pipeline_error"]]
    verified_sources = sum(r["checks"]["verified_sources"] for r in records)
    unverified_sources = sum(r["checks"]["unverified_sources"] for r in records)
    llm_quotes = sum(r["checks"]["llm_quotes"] for r in records)
    unmatched = sum(r["checks"]["unmatched_quotes"] for r in records)
    lengths = [r["checks"]["answer_chars"] for r in usable]
    clean_lengths = [r["checks"]["answer_chars"] for r in clean]
    authorities = [s for r in usable if r["expected"] == "answerable" for s in r.get("required_sources") or []]
    answerable = [r for r in usable if r["expected"] == "answerable"]
    multi = [r for r in answerable if len(r.get("required_sources") or []) > 1]
    case_records = [r for r in answerable if any(s.get("kind") == "case_law" for s in r.get("required_sources") or [])]
    case_ok = [r for r in case_records if r["retrieved_all_required_sources"] and not {"grader_unsupported_claims", "grader_does_not_answer_question"} & set(r["status_reasons"])]
    timings = [r["teacher"]["timings"] for r in usable if r["teacher"].get("timings")]
    attempt_reasons = Counter(a["reason"] for a in attempts)
    created = sorted(r["created_at"] for r in records)
    question_times = sorted((q.get("generator") or {}).get("created_at") for q in questions if (q.get("generator") or {}).get("created_at"))
    started = min(filter(None, [question_times[0] if question_times else None, created[0] if created else None]))
    runtime_h = (datetime.fromisoformat(created[-1]) - datetime.fromisoformat(started)).total_seconds() / 3600 if created else None

    cited_types, cited_acts, retrieved_types, act_distribution = Counter(), Counter(), Counter(), Counter()
    for record in records:
        for citation in record["citations"]:
            cited_types[citation.get("source_type")] += 1
            cited_acts[citation.get("act_title") or "Judgment"] += 1
        for doc in record["retrieved_context"]:
            retrieved_types[doc.get("source_type")] += 1
    for record in clean:
        act_distribution[act_of(record)] += 1

    report = {
        "run": args.run,
        "questions_generated": len(questions),
        "question_generation": {
            "candidates_processed": len(attempts), "accepted": attempt_reasons.get("accepted", 0),
            "rejected_by_reason": {k: v for k, v in attempt_reasons.most_common() if k != "accepted"},
            "duplicate_rejections": sum(attempt_reasons.get(k, 0) for k in ("duplicate_question", "near_duplicate_question", "duplicate_seed")),
            "duplicate_rate_of_candidates": rate(sum(attempt_reasons.get(k, 0) for k in ("duplicate_question", "near_duplicate_question", "duplicate_seed")), len(attempts)),
            "accepted_questions_sharing_category_and_seed": len(questions) - len({(q["category"], tuple(q["seed"]["doc_ids"])) for q in questions}),
            "false_insufficient_labels_rejected": sum(v for k, v in attempt_reasons.items() if k.startswith("insufficient_label_rejected")),
        },
        "examples_generated": len(records),
        "quality_status": {s: len(by_status[s]) for s in ("VERIFIED", "NEEDS_REVIEW", "REJECTED")},
        "clean_examples": len(clean),
        "split": {name: len(splits[name]) for name in ("train", "validation", "test")},
        "split_groups": group_info,
        "leakage": leakage(clean, split_of),
        "citation_verification_rate": rate(verified_sources, verified_sources + unverified_sources),
        "unverified_citations": unverified_sources,
        "evidence_quote_match_rate": rate(llm_quotes - unmatched, llm_quotes),
        "examples_with_verified_citation": rate(sum(1 for r in records if r["checks"]["verified_sources"]), len(records)),
        "intended_source_recall": rate(sum(1 for s in authorities if s["retrieved_doc_ids"]), len(authorities)),
        "examples_with_any_required_source": f"{sum(1 for r in answerable if r['checks']['seed_retrieved'])}/{len(answerable)}",
        "examples_with_all_required_sources": f"{sum(1 for r in answerable if r['retrieved_all_required_sources'])}/{len(answerable)}",
        "multi_authority_all_retrieved": f"{sum(1 for r in multi if r['retrieved_all_required_sources'])}/{len(multi)}",
        "case_law_validation": {
            "examples": len(case_records), "authority_retrieved_and_answer_supported": len(case_ok),
            "accuracy": rate(len(case_ok), len(case_records)),
            "by_type": dict(Counter(r.get("case_law_type") for r in case_records)),
        },
        "insufficiency": {
            "true_insufficient": sum(1 for r in usable if r.get("insufficiency_classification") == "TRUE_INSUFFICIENT"),
            "false_insufficient_retrieval_failure": sum(1 for r in usable if r.get("insufficiency_classification") == "FALSE_INSUFFICIENT_RETRIEVAL_FAILURE"),
            "false_insufficient_in_verified": sum(1 for r in clean if r.get("insufficiency_classification") == "FALSE_INSUFFICIENT_RETRIEVAL_FAILURE"),
            "refusal_training_eligible": sum(1 for r in clean if r.get("refusal_training_eligible")),
            "partial_with_required_sources": sum(1 for r in usable if r.get("insufficiency_classification") == "PARTIAL_WITH_REQUIRED_SOURCES"),
        },
        "internal_markup_leaks": sum(1 for r in records if r["checks"].get("internal_markup_leak")),
        "per_category": {
            category: {"questions": n, **{s: sum(1 for r in records if r["category"] == category and status_of(r) == s) for s in ("VERIFIED", "NEEDS_REVIEW", "REJECTED")}}
            for category, n in Counter(q["category"] for q in questions).items()
        },
        "clean_category_distribution": dict(Counter(r["category"] for r in clean)),
        "clean_act_distribution": dict(act_distribution.most_common()),
        "clean_statute_vs_case_law": dict(Counter(
            "case_law_and_statute" if {s.get("kind") for s in r.get("required_sources") or []} >= {"case_law", "statute"}
            else "case_law" if any(s.get("kind") == "case_law" for s in r.get("required_sources") or [])
            else "none (insufficient)" if not r.get("required_sources") else "statute"
            for r in clean
        )),
        "answer_types": dict(Counter(r["answer_type"] for r in records if r["answer_type"])),
        "answer_length_chars": {
            "average": round(mean(lengths)) if lengths else None, "median": round(median(lengths)) if lengths else None,
            "long_answer_pct": round(100 * sum(1 for n in lengths if n > LONG_ANSWER_CHARS) / len(lengths), 1) if lengths else None,
            "clean_average": round(mean(clean_lengths)) if clean_lengths else None,
            "clean_median": round(median(clean_lengths)) if clean_lengths else None,
        },
        "source_diversity": {
            "distinct_cited_sources": len({c["doc_id"] for r in clean for c in r["citations"]}),
            "distinct_acts_in_clean": len(act_distribution),
        },
        "cited_source_types": dict(cited_types),
        "retrieved_source_types": dict(retrieved_types),
        "top_cited_sources": cited_acts.most_common(15),
        "needs_review_reasons": dict(Counter(reason for r in by_status["NEEDS_REVIEW"] for reason in r["status_reasons"])),
        "rejected_reasons": dict(Counter(reason for r in by_status["REJECTED"] for reason in r["status_reasons"])),
        "grader_errors": sum(1 for r in records if (r.get("grader") or {}).get("error")),
        "generation_failures": {
            "pipeline_errors_final": sum(1 for r in records if r["checks"]["pipeline_error"]),
            "teacher_retries": sum(max(0, r["teacher"]["pipeline_attempts"] - 1) for r in records),
            "failure_log": dict(Counter(f"{f['stage']}:{f['reason']}" for f in failures)),
        },
        "average_latency_s": {
            key: round(mean(t[key] for t in timings if key in t), 2) for key in ("retrieval_s", "generation_s", "total_s")
        } if timings else None,
        "runtime_hours": round(runtime_h, 2) if runtime_h is not None else None,
    }
    (run / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (run / "report.md").write_text(render_markdown(report))
    print(json.dumps(report, indent=2, ensure_ascii=False))


def render_markdown(report):
    def table(mapping, headers=("Item", "Count")):
        rows = "\n".join(f"| {k} | {v} |" for k, v in mapping.items())
        return f"| {headers[0]} | {headers[1]} |\n|---|---|\n{rows}"

    status = report["quality_status"]
    lines = [
        f"# Teacher Dataset Report — {report['run']}", "",
        "## Totals", "",
        table({
            "Questions generated": report["questions_generated"], "Examples generated": report["examples_generated"],
            "VERIFIED": status["VERIFIED"], "NEEDS_REVIEW": status["NEEDS_REVIEW"], "REJECTED": status["REJECTED"],
            "Clean examples": report["clean_examples"], "Train": report["split"]["train"],
            "Validation": report["split"]["validation"], "Test": report["split"]["test"],
        }), "",
        "## Evidence and citations", "",
        table({
            "Citation verification rate": report["citation_verification_rate"], "Unverified citations": report["unverified_citations"],
            "Evidence quote match rate": report["evidence_quote_match_rate"],
            "Intended-source recall": report["intended_source_recall"],
            "Examples with any required source": report["examples_with_any_required_source"],
            "Examples with all required sources": report["examples_with_all_required_sources"],
            "Multi-authority all retrieved": report["multi_authority_all_retrieved"],
            "Internal markup leaks": report["internal_markup_leaks"],
        }), "",
        "## Insufficiency", "", table(report["insufficiency"]), "",
        "## Case law", "", table({k: v for k, v in report["case_law_validation"].items() if k != "by_type"}), "",
        "## Answer length (characters)", "", table(report["answer_length_chars"]), "",
        "## Split leakage checks", "", table({**report["leakage"], **report["split_groups"]}), "",
        "## Clean category distribution", "", table(report["clean_category_distribution"]), "",
        "## Clean statute vs case law", "", table(report["clean_statute_vs_case_law"]), "",
        "## Clean Act distribution (top 25)", "", table(dict(list(report["clean_act_distribution"].items())[:25])), "",
        "## Question generation", "",
        table({k: v for k, v in report["question_generation"].items() if k != "rejected_by_reason"}), "",
        "Rejected candidates by reason:", "", table(report["question_generation"]["rejected_by_reason"]), "",
        "## Review and rejection reasons", "", table(report["needs_review_reasons"]), "", table(report["rejected_reasons"]), "",
        "## Failures and runtime", "",
        table({**{k: v for k, v in report["generation_failures"].items() if k != "failure_log"},
               "Grader errors": report["grader_errors"], "Runtime (hours)": report["runtime_hours"],
               "Average latency (s)": report["average_latency_s"]}), "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
