"""
Evaluation harness for the RAG pipeline.

Runs a fixed set of test questions through answer_question() and reports
citation-verification health: how many questions got at least one verified
citation, how many produced an unverified (potentially hallucinated)
citation, and latency. This is intentionally not a golden-answer scorer —
grading legal-answer *correctness* needs a human review pass or a much
larger labeled set — it's a regression guard for the one thing this system
promises never to get wrong: presenting a citation as verified when it isn't.

Usage:
    python evaluate_rag.py                                    # data/eval/eval_questions.json
    python evaluate_rag.py --questions path/to/questions.json
    python evaluate_rag.py --out data/eval/results/run.json    # also write a JSON report
"""
import argparse
import json
import os
import time

from logging_config import get_logger
from rag_chain import answer_question

logger = get_logger("evaluate_rag")

DEFAULT_QUESTIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "eval", "eval_questions.json")


def load_questions(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_eval(questions_path: str = DEFAULT_QUESTIONS_PATH, top_k: int = 5):
    questions = load_questions(questions_path)
    results = []

    for i, q in enumerate(questions, 1):
        question_text = q["question"]
        expect_citation = q.get("expect_citation", True)

        logger.info("[%d/%d] %s", i, len(questions), question_text)
        t0 = time.perf_counter()
        try:
            result = answer_question(question_text, top_k=top_k)
            error = None
        except Exception as e:
            logger.exception("Question failed: %s", question_text)
            result = None
            error = str(e)
        latency = time.perf_counter() - t0

        if result is None:
            results.append({
                "question": question_text, "error": error, "latency_sec": round(latency, 3),
                "passed": False,
            })
            continue

        got_citation = len(result.get("verified", [])) > 0
        has_unverified = len(result.get("unverified", [])) > 0
        # Pass = citation presence matched expectation AND nothing slipped through unverified.
        passed = (got_citation == expect_citation) and not has_unverified

        results.append({
            "question": question_text,
            "expect_citation": expect_citation,
            "got_verified_citation": got_citation,
            "unverified_citations": result.get("unverified", []),
            "accuracy_note": result.get("accuracy_note"),
            "latency_sec": round(latency, 3),
            "passed": passed,
            "answer": result.get("clean_answer"),
        })

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    any_unverified = sum(1 for r in results if r.get("unverified_citations"))
    avg_latency = sum(r["latency_sec"] for r in results) / total if total else 0.0

    summary = {
        "total_questions": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "questions_with_unverified_citations": any_unverified,
        "avg_latency_sec": round(avg_latency, 3),
    }
    return {"summary": summary, "results": results}


def print_report(report: dict):
    print("\n================ RAG EVALUATION ================")
    for r in report["results"]:
        status = "PASS" if r["passed"] else "FAIL"
        note = r.get("error") or r.get("accuracy_note", "")
        print(f"[{status}] ({r['latency_sec']:.2f}s) {r['question'][:70]} - {note}")
    print("--------------------------------------------------")
    s = report["summary"]
    print(f"Passed: {s['passed']}/{s['total_questions']} ({s['pass_rate'] * 100:.1f}%)")
    print(f"Questions with an unverified citation: {s['questions_with_unverified_citations']}")
    print(f"Average latency: {s['avg_latency_sec']:.2f}s")
    print("==================================================\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--top_k", type=int, default=5)
    parser.add_argument("--out", default=None, help="Optional path to also write the full JSON report")
    args = parser.parse_args()

    report = run_eval(args.questions, top_k=args.top_k)
    print_report(report)

    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Full report written to {args.out}")


if __name__ == "__main__":
    main()
