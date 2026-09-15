"""
Scores base vs fine-tuned Qwen outputs (from generate_eval.py) with the same machinery that graded the
Claude teacher, so the comparison is like-for-like:

  1. parse the raw output with the app's own JSON/citation recovery helpers (src/llm_provider.py);
  2. run it through rag_chain.answer_question() with retrieval replaced by the stored evidence and the
     model call replaced by the parsed output — the prompt is rebuilt and checked against the one the
     model actually saw, then citation mapping and citation verification run unchanged;
  3. apply the teacher quality checks, and with --grade the same Claude grader and quality gates.

Run with the app venv (needs src/ dependencies):
    .venv/bin/python distill/finetune/score_eval.py --labels base lora --prompts distill/finetune/data/eval_prompts_pilot_v2.jsonl [--grade]
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "distill"))

import generate_teacher as teacher  # noqa: E402  (also puts src/ on sys.path)
import rag_chain  # noqa: E402
from llm_provider import _coerce_citations, _extract_json_object, _recover_embedded_citations, _sanitize_citations  # noqa: E402


def parse_output(text):
    """Same recovery path the app uses for local-model output."""
    content = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
    # Strictly valid structured output: the whole object parses as JSON with a non-empty answer and a
    # citations list. The app's salvage helpers below can still recover pieces of a malformed object,
    # which must not be counted as valid.
    try:
        strict = json.loads(content[content.find("{"): content.rfind("}") + 1])
        valid = (isinstance(strict, dict) and isinstance(strict.get("citations"), list)
                 and isinstance(strict.get("answer"), str) and bool(strict["answer"].strip()))
    except (ValueError, TypeError):
        valid = False
    parsed = _extract_json_object(content)
    if not parsed:
        return {"answer": content, "citations": []}, valid
    answer, embedded = _recover_embedded_citations(str(parsed.get("answer") or ""))
    citations = _sanitize_citations(_coerce_citations(parsed.get("citations")) + embedded)
    return {"answer": answer, "citations": citations}, valid


def hits_from(item):
    hits = []
    for doc in item["retrieved_context"]:
        hits.append({
            "doc_id": doc["doc_id"], "title": doc.get("title"), "source_type": doc.get("source_type"),
            "court": doc.get("court"), "date": doc.get("date"), "section": doc.get("chunk_label"),
            "file_name": None, "page_start": None, "page_end": None, "text": doc.get("text") or "",
            "source": doc.get("retrieval"), "score": doc.get("score"), "rerank_score": doc.get("rerank_score"),
            "retrieval_ranks": doc.get("retrieval_ranks"), "required_reason": doc.get("required_reason"),
            "chunk_id": doc.get("chunk_id"), "chunk_ids": doc.get("chunk_ids"), "context_span": doc.get("context_span"),
        })
    return hits


class ReplayProvider:
    def __init__(self, output):
        self.output = output

    def generate_structured_answer(self, system_prompt, user_content):
        return self.output


def score_one(item, generation, grade_with_claude):
    parsed, json_ok = parse_output(generation["output"])
    hits = hits_from(item)
    rag_chain.hybrid_search_with_plan = lambda question, top_k=5, on_stage=None: (hits, {})
    rag_chain.get_llm_provider = lambda: ReplayProvider(parsed)
    # Use the instruction embedded in the stored prompt: the dataset instruction was revised during the pilot,
    # and the model saw the prompt exactly as stored.
    marker = f"Question: {item['question']}\n\n"
    instruction = item["user"].split(marker, 1)[1] if marker in item["user"] else teacher.TEACHER_INSTRUCTION
    result = rag_chain.answer_question(item["question"], top_k=5, answer_instruction=instruction)
    prompt_matches = result.get("user_content") == item["user"]

    question = {"id": item["id"], "question": item["question"], "category": item["category"], "seed": item["seed"],
                **(item.get("question_record") or {}), "expected": item["expected"]}
    answer = result.get("answer_markdown") or ""
    retrieved = result.get("retrieved_documents") or []
    citations = [{"number": c["number"], "doc_id": c["doc_id"], "verified": c["verified"], "evidence_quotes": c.get("quotes") or []}
                 for c in result.get("citations") or []]
    checks = teacher.quality_checks(question, result, answer, citations, retrieved)
    row = {
        "id": item["id"], "source_run": item["source_run"], "category": item["category"], "expected": item["expected"],
        "json_ok": json_ok, "prompt_matches": prompt_matches, "truncated": generation["output_tokens"] >= 1195,
        "output_tokens": generation["output_tokens"], "seconds": generation["seconds"],
        "answer_chars": len(answer), "llm_quotes": checks["llm_quotes"], "unmatched_quotes": checks["unmatched_quotes"],
        "verified_sources": checks["verified_sources"], "unverified_sources": checks["unverified_sources"],
        "markers": bool(checks["inline_markers"]), "markers_without_source": bool(checks["markers_without_source"]),
        "states_insufficiency": checks["states_insufficiency"], "internal_leak": checks["internal_markup_leak"],
        "required_all_retrieved": checks["seed_all_retrieved"], "answer": answer,
        "answer_lost": not (parsed.get("answer") or "").strip(),
        "verified_doc_ids": [c["doc_id"] for c in citations if c["verified"]],
        "retrieved_doc_ids": [d["doc_id"] for d in retrieved],
        "excerpts": [{"doc_id": d["doc_id"], "title": d.get("title"), "source_type": d.get("source_type"), "text": d.get("excerpt") or ""} for d in retrieved],
    }
    if grade_with_claude:
        judge = teacher.run_judge(question, result, answer)
        if not judge.get("error"):
            teacher.confirm_principle_equivalents(checks, retrieved, judge)
        status, reasons, answer_type, classification = teacher.grade(question, checks, judge)
        row.update({"quality_status": status, "status_reasons": reasons, "answer_type": answer_type,
                    "grader": {k: judge.get(k) for k in ("supported", "invented_authority", "answers_question", "answer_type", "insufficiency_justified", "concise", "error")}})
    return row


def summarise(rows):
    n = len(rows)
    rate = lambda f: round(100 * sum(1 for r in rows if f(r)) / n, 1) if n else None  # noqa: E731
    quotes = sum(r["llm_quotes"] for r in rows)
    summary = {
        "examples": n,
        "valid_json_pct": rate(lambda r: r["json_ok"]),
        "answers_with_verified_citation_pct": rate(lambda r: r["verified_sources"] > 0),
        "verified_citations_total": sum(r["verified_sources"] for r in rows),
        "unverified_citations_total": sum(r["unverified_sources"] for r in rows),
        "evidence_quote_match_pct": round(100 * (quotes - sum(r["unmatched_quotes"] for r in rows)) / quotes, 1) if quotes else None,
        "inline_citation_markers_pct": rate(lambda r: r["markers"]),
        "internal_markup_leak_pct": rate(lambda r: r["internal_leak"]),
        "truncated_at_max_tokens_pct": rate(lambda r: r["truncated"]),
        "answer_chars_median": median(r["answer_chars"] for r in rows) if rows else None,
        "seconds_mean": round(mean(r["seconds"] for r in rows), 1) if rows else None,
        "insufficient_questions_refused_pct": (
            round(100 * sum(1 for r in rows if r["expected"] == "insufficient" and r["states_insufficiency"])
                  / max(1, sum(1 for r in rows if r["expected"] == "insufficient")), 1)),
        "prompt_reconstruction_matches": sum(1 for r in rows if r["prompt_matches"]),
    }
    if rows and "quality_status" in rows[0]:
        summary.update({
            "VERIFIED_pct": rate(lambda r: r["quality_status"] == "VERIFIED"),
            "REJECTED_pct": rate(lambda r: r["quality_status"] == "REJECTED"),
            "grader_supported_pct": rate(lambda r: r["grader"].get("supported")),
            "grader_invented_authority_pct": rate(lambda r: r["grader"].get("invented_authority")),
            "grader_answers_question_pct": rate(lambda r: r["grader"].get("answers_question")),
        })
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", nargs="+", required=True)
    parser.add_argument("--prompts", required=True)
    parser.add_argument("--grade", action="store_true", help="Also run the Claude grader and quality gates.")
    args = parser.parse_args()

    items = {f"{i['id']}|{i['source_run']}": i for i in (json.loads(l) for l in Path(args.prompts).read_text().splitlines() if l.strip())}
    report = {"prompts": args.prompts, "graded": args.grade, "models": {}}
    for label in args.labels:
        outputs = [json.loads(l) for l in (HERE / "eval" / f"outputs_{label}.jsonl").read_text().splitlines() if l.strip()]
        rows = [score_one(items[f"{o['id']}|{o['source_run']}"], o, args.grade) for o in outputs if f"{o['id']}|{o['source_run']}" in items]
        by_category = defaultdict(list)
        for row in rows:
            by_category[row["category"]].append(row)
        report["models"][label] = {"overall": summarise(rows), "by_category": {c: summarise(r) for c, r in by_category.items()}, "rows": rows}
        print(label, json.dumps(report["models"][label]["overall"], indent=1))
    suffix = "_graded" if args.grade else ""
    (HERE / "eval" / f"scores{suffix}_{Path(args.prompts).stem}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
