"""
Offline checks for the question-generator / grader fixes (no Claude calls, no pilot files written).

A. insufficient_evidence validation — verify_insufficient() with stubbed checker responses on the
   IPC Section 40 question; legacy pilot records re-graded in memory.
B. principle-based case law — authorities built from a verbatim principle phrase accept equivalent
   judgments; a non-verbatim phrase is rejected.
C. multiple authorities — pilot records re-graded in memory with all-authority coverage.
D. tool markup — stripped from hints; questions containing markup are rejected.

Usage (from the repository root):
    .venv/bin/python distill/diagnostics/test_checker_fixes.py
"""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "distill"))

from build_questions import MARKUP, Corpus, seed_authorities, strip_markup, verify_insufficient  # noqa: E402
from common import latest_by_id, read_jsonl  # noqa: E402
from generate_teacher import grade, refusal_training_eligible, seed_coverage  # noqa: E402

PILOT = ROOT / "data" / "distill" / "pilot"
OUT = PILOT / "retrieval_fix" / "checker_fix_tests.json"
failures = []


def check(name, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def main():
    questions = {q["id"]: q for q in read_jsonl(PILOT / "questions.jsonl")}
    records = latest_by_id(read_jsonl(PILOT / "teacher_records.jsonl"))
    corpus = Corpus()
    results = {}

    print("--- D. tool markup ---")
    hint = questions["q-cee5a99865bb"]["seed"]["answer_hint"]
    cleaned = strip_markup(hint)
    check("leaked markup present in the original pilot hint", bool(MARKUP.search(hint)))
    check("markup stripped from hint", not MARKUP.search(cleaned) and cleaned.endswith("413 BNSS."), repr(cleaned[-60:]))
    check("question containing markup is detected", bool(MARKUP.search('What is bail?</question>\n<parameter name="x">')))
    check("ordinary legal text is not treated as markup", not MARKUP.search("Section 138 < Section 139 and the 'a bank' vs 'the bank' point"))
    results["D"] = {"original_hint_tail": hint[-80:], "cleaned_hint_tail": cleaned[-80:]}

    print("\n--- A. insufficient_evidence validation (IPC s40) ---")
    q40 = questions["q-69d6210ebe23"]
    seed = {"passages": [{"doc_id": d, "label": l, "text": corpus.statutes[d]["text"]} for d, l in zip(q40["seed"]["doc_ids"], q40["seed"]["labels"])]}
    no_retrieval = lambda q: []  # noqa: E731
    verdicts = {}
    for name, response in {
        "checker finds the answer in the seed": {"answerable": True, "supporting_quote": "punishable under such law with imprisonment for a term of six months or upwards"},
        "checker claims an answer it cannot quote": {"answerable": True, "supporting_quote": "a minimum term of one year is required"},
        "checker finds no answer": {"answerable": False, "supporting_quote": ""},
    }.items():
        verdicts[name] = verify_insufficient(q40["question"], seed, corpus, ask=lambda *a, r=response, **k: r, retrieve=no_retrieval)
    check("label rejected when the seed answers the question", verdicts["checker finds the answer in the seed"]["verdict"] == "answerable")
    check("label rejected when the claimed answer is not verbatim", verdicts["checker claims an answer it cannot quote"]["verdict"] == "answerable_unverified_quote")
    check("label kept only when no answer is found", verdicts["checker finds no answer"]["verdict"] == "insufficient")
    results["A_verdicts"] = {k: {x: v[x] for x in ("verdict", "quote_found_in_passages", "checked_doc_ids")} for k, v in verdicts.items()}

    print("\n--- A/C. pilot records re-graded in memory (legacy questions, no files written) ---")
    changes = []
    for rid, record in records.items():
        question = questions[rid]
        retrieved = [d["doc_id"] for d in record["retrieved_context"]]
        cited = [c["doc_id"] for c in record["citations"]]
        checks = {**record["checks"], **seed_coverage(question, retrieved, cited)}
        status, reasons, _ = grade(question, checks)
        eligible = refusal_training_eligible(question, checks, status)
        if status != record["status"] or reasons != record["status_reasons"]:
            changes.append({"id": rid, "category": record["category"], "old_status": record["status"], "new_status": status,
                            "old_reasons": record["status_reasons"], "new_reasons": reasons, "refusal_training_eligible": eligible})
    for change in changes:
        print(f"  {change['id']} {change['category']:22} {change['old_status']} -> {change['new_status']}  added={sorted(set(change['new_reasons']) - set(change['old_reasons']))}")
    by_id = {c["id"]: c for c in changes}
    check("IPC s40 record: label now flagged as unvalidated, not refusal data",
          "insufficiency_label_unvalidated" in by_id.get("q-69d6210ebe23", {}).get("new_reasons", [])
          and not by_id.get("q-69d6210ebe23", {}).get("refusal_training_eligible", True))
    check("multi-section record with 1 of 2 sections retrieved is no longer 'verified'",
          by_id.get("q-5c502c87752e", {}).get("new_reasons") == ["some_seed_sources_not_retrieved"])
    eligible_total = 0
    for rid, record in records.items():
        question = questions[rid]
        checks = {**record["checks"], **seed_coverage(question, [d["doc_id"] for d in record["retrieved_context"]], [c["doc_id"] for c in record["citations"]])}
        status, _, _ = grade(question, checks)
        eligible_total += refusal_training_eligible(question, checks, status)
    check("no legacy pilot record is eligible as refusal training data (none was validated)", eligible_total == 0, f"eligible={eligible_total}")
    results["regrade_changes"] = changes

    print("\n--- B. principle-based case law ---")
    q89 = questions["q-89d14510bd1b"]
    record89 = records["q-89d14510bd1b"]
    judgment = next(j for j in corpus.judgments if j["doc_id"] == q89["seed"]["doc_ids"][0])
    full_text = html.unescape(judgment["full_text"])
    # Illustration only: the phrase is supplied by hand here; the pilot question record is not changed.
    phrase = "within 15 days of receipt of the summons"
    start = full_text.lower().find(phrase)
    check("illustrative phrase occurs in the seed judgment", start >= 0)
    passage = {"doc_id": judgment["doc_id"], "label": judgment["title"], "text": full_text[max(0, start - 400): start + 400]}
    verbatim = full_text[start:start + len(phrase)]
    authorities, problem = seed_authorities({"passages": [passage]}, {"principle_phrase": verbatim}, corpus)
    check("verbatim principle phrase yields an equivalence set", problem is None and bool(authorities) and len(authorities[0]["doc_ids"]) > 1,
          f"equivalent judgments={len(authorities[0]['doc_ids']) if authorities else 0}")
    _, bad = seed_authorities({"passages": [passage]}, {"principle_phrase": "the court held that the accused can never dispute service of notice"}, corpus)
    check("non-verbatim principle phrase is rejected", bad == "principle_phrase_not_verbatim")
    named_authorities, named_problem = seed_authorities({"passages": [passage]}, {"names_specific_case": True}, corpus)
    check("a question naming the case keeps the exact judgment",
          named_problem is None and named_authorities[0]["equivalence"] == "exact" and named_authorities[0]["doc_ids"] == [judgment["doc_id"]])
    if authorities:
        simulated = {**q89, "seed": {**q89["seed"], "authorities": authorities}}
        legacy = seed_coverage(q89, [d["doc_id"] for d in record89["retrieved_context"]], [])
        principled = seed_coverage(simulated, [d["doc_id"] for d in record89["retrieved_context"]], [])
        print(f"  q-89d14510bd1b seed coverage: exact-seed rule={legacy['seed_authorities_retrieved']}  principle rule={principled['seed_authorities_retrieved']}")
        results["B_simulation"] = {"phrase": authorities[0]["principle_phrase"], "equivalents": len(authorities[0]["doc_ids"]),
                                   "exact_rule": legacy, "principle_rule": principled}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"failures": failures, **results}, indent=2, ensure_ascii=False))
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
