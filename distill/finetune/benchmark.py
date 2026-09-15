"""
Answer-engine benchmark: Claude API vs LoRA Qwen + RAG vs Plain Qwen (base) + RAG, through the real app path.

Every model answers every question of the frozen held-out benchmark (distill/finetune/data/eval_prompts_pilot_v2.jsonl)
from the IDENTICAL stored RAG evidence and prompt, via src/engines.py — the same provider, structured-output
validation, retry policy, citation mapping and citation verification the research UI uses. Nothing is retrieved
again, and no question, evidence or reference answer is changed.

Scoring reuses the LoRA pilot machinery unchanged:
  * deterministic checks: generate_teacher.quality_checks on the app result (citations produced / verified /
    unverified, evidence-quote match, markers, leaks, insufficiency wording, length);
  * blind Claude rubric and the pre-registered overall score: pilot_lora_grade.rubric / overall;
  * aggregates: pilot_lora_report.aggregate.

The report keeps LEGAL QUALITY (correctness, support, hallucination, refusals) separate from FORMAT / CITATION
behaviour (valid / malformed / truncated / failed output, retries, citation accuracy), so an improvement in
formatting alone is never presented as a legal-quality improvement.

Resumable: records.jsonl is appended per (model, question); a rerun skips finished pairs.

Usage (app venv; start the LoRA service and Ollama first):
    .venv/bin/python distill/finetune/benchmark.py benchmark --models claude,qwen,lora_qwen [--limit 5] [--run NAME]
    .venv/bin/python distill/finetune/benchmark.py report --run NAME
"""
import argparse
import csv
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "distill"))

import pilot_lora_grade  # noqa: E402  (imports score_eval → generate_teacher → src/ on sys.path)
import score_eval  # noqa: E402
import generate_teacher as teacher  # noqa: E402
from common import read_jsonl  # noqa: E402
import engines  # noqa: E402
import rag_chain  # noqa: E402
from pilot_lora_report import aggregate, pct  # noqa: E402

PROMPTS = HERE / "data" / "eval_prompts_pilot_v2.jsonl"
OUT_ROOT = ROOT / "data" / "distill" / "engine_benchmark"
LOCAL_ENGINES = {"qwen", "lora_qwen"}  # one local model generates at a time (8 GB unified memory)
_write_lock = threading.Lock()


def evidence_for(item):
    hits = score_eval.hits_from(item)
    return {"question": item["question"], "top_k": 5, "hits": hits, "retrieval_plan": {}, "error": None, "retrieval_s": 0.0,
            "reused": True, "created_at": time.time(), "evidence_id": rag_chain.evidence_fingerprint(item["question"], 5, hits)}


def stored_instruction(item):
    marker = f"Question: {item['question']}\n\n"
    return item["user"].split(marker, 1)[1] if marker in item["user"] else teacher.TEACHER_INSTRUCTION


def deterministic(item, result):
    engine = result["engine"]
    retrieved = result.get("retrieved_documents") or []
    answer = result.get("answer_markdown") or ""
    failed = result.get("error") == "generation"
    question = {"id": item["id"], "question": item["question"], "category": item["category"], "seed": item["seed"],
                **(item.get("question_record") or {}), "expected": item["expected"]}
    citations = [{"number": c["number"], "doc_id": c["doc_id"], "verified": c["verified"], "evidence_quotes": c.get("quotes") or []}
                 for c in result.get("citations") or []]
    if failed:
        answer = ""
        checks = {"llm_quotes": 0, "unmatched_quotes": 0, "verified_sources": 0, "unverified_sources": 0, "inline_markers": [],
                  "markers_without_source": [], "states_insufficiency": False, "internal_markup_leak": False, "seed_all_retrieved": None}
    else:
        checks = teacher.quality_checks(question, result, answer, citations, retrieved)
    final_raw = (result.get("engine_attempts") or [{}])[-1].get("raw_output") or ""
    parsed, _ = score_eval.parse_output(final_raw)
    return {
        "id": item["id"], "source_run": item["source_run"], "category": item["category"], "expected": item["expected"],
        "output_status": engine["output_status"], "first_output_status": engine.get("first_output_status"),
        "retry_count": engine["retry_count"], "json_ok": engine["output_status"] == "VALID",
        "truncated": engine["output_status"] == "TRUNCATED", "failed": failed, "error": engine.get("error"),
        "prompt_matches": result.get("user_content") == item["user"], "output_tokens": engine.get("output_tokens"),
        "seconds": engine.get("generation_s"), "answer_chars": len(answer),
        "llm_quotes": checks["llm_quotes"], "unmatched_quotes": checks["unmatched_quotes"],
        "verified_sources": checks["verified_sources"], "unverified_sources": checks["unverified_sources"],
        "markers": bool(checks["inline_markers"]), "markers_without_source": bool(checks["markers_without_source"]),
        "states_insufficiency": checks["states_insufficiency"], "internal_leak": checks["internal_markup_leak"],
        "required_all_retrieved": checks["seed_all_retrieved"], "answer": answer,
        "answer_lost": failed or not (parsed.get("answer") or "").strip(),
        "verified_doc_ids": [c["doc_id"] for c in citations if c["verified"]],
        "retrieved_doc_ids": [d["doc_id"] for d in retrieved],
        "excerpts": [{"doc_id": d["doc_id"], "title": d.get("title"), "source_type": d.get("source_type"), "text": d.get("excerpt") or ""} for d in retrieved],
    }


def run_one(model, item, out):
    evidence = evidence_for(item)
    result = engines.generate_with_engine(item["question"], model, evidence, mode="research", answer_instruction=stored_instruction(item))
    row = deterministic(item, result)
    grade = pilot_lora_grade.rubric(item, row)
    record = {
        "model": model, "key": f"{item['id']}|{item['source_run']}", "id": item["id"], "category": item["category"],
        "expected": item["expected"], "question": item["question"], "evidence_id": evidence["evidence_id"],
        "engine": {k: v for k, v in result["engine"].items() if k not in ("error",)},
        "attempts": [{k: v for k, v in a.items() if k != "raw_output"} | {"raw_output": (a.get("raw_output") or "")[:4000]}
                     for a in result.get("engine_attempts") or []],
        "deterministic": {k: v for k, v in row.items() if k != "excerpts"},
        "rubric": grade, "overall": pilot_lora_grade.overall(row, grade), "latency_s": row["seconds"],
    }
    with _write_lock, (out / "records.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def engine_metrics(rows):
    n = len(rows)
    d = [r["deterministic"] for r in rows]
    status = lambda s: sum(1 for x in d if x["output_status"] == s)  # noqa: E731
    answerable = [r for r in rows if r["expected"] != "insufficient" and not r["rubric"].get("error")]
    return {
        "valid_output": status("VALID"), "malformed_output": status("MALFORMED"), "truncated_output": status("TRUNCATED"),
        "failed_output": status("FAILED"), "first_attempt_valid": sum(1 for x in d if x["first_output_status"] == "VALID"),
        "retries_total": sum(x["retry_count"] for x in d), "prompt_identical": sum(1 for x in d if x["prompt_matches"]),
        "wrong_refusals_on_answerable": sum(1 for r in answerable if not r["rubric"]["abstention_correct"]),
        "answerable_questions": len(answerable), "questions": n,
        "output_tokens_median": statistics.median([x["output_tokens"] for x in d if x["output_tokens"]] or [0]),
    }


def report(out, models):
    records = {}
    for record in read_jsonl(out / "records.jsonl"):
        records[(record["model"], record["key"])] = record
    items = read_jsonl(PROMPTS)
    present = [m for m in models if any((m, f"{i['id']}|{i['source_run']}") in records for i in items)]
    rows = {m: [records[(m, f"{i['id']}|{i['source_run']}")] for i in items if (m, f"{i['id']}|{i['source_run']}") in records] for m in present}
    aggs = {m: {**aggregate(rows[m]), **engine_metrics(rows[m])} for m in present}
    evidence_ids = {i["id"]: [records[(m, f"{i['id']}|{i['source_run']}")]["evidence_id"] for m in present
                              if (m, f"{i['id']}|{i['source_run']}") in records] for i in items}
    evidence_ids = {q: ids for q, ids in evidence_ids.items() if ids}
    identical = sum(1 for ids in evidence_ids.values() if len(ids) == len(present) and len(set(ids)) == 1)
    n_run = len(evidence_ids)
    names = {m: engines.engine_spec(m)["subtitle"] for m in present}
    (out / "benchmark_results.json").write_text(json.dumps({"benchmark": str(PROMPTS.relative_to(ROOT)), "models": names, "aggregates": aggs,
                                                             "questions_with_identical_evidence": identical}, indent=2, ensure_ascii=False))
    with (out / "benchmark_results.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["model", "question_id", "category", "expected", "evidence_id", "overall", "legal_correctness", "evidence_support",
                         "hallucination", "structure", "abstention_correct", "output_status", "first_output_status", "retries",
                         "citations_produced", "verified_citations", "unverified_citations", "answer_chars", "generation_s", "grading_error", "answer"])
        for m in present:
            for r in rows[m]:
                d, g = r["deterministic"], r["rubric"]
                writer.writerow([m, r["id"], r["category"], r["expected"], r["evidence_id"], r["overall"], g.get("legal_correctness"),
                                 g.get("evidence_support"), g.get("hallucination"), g.get("structure"), g.get("abstention_correct"),
                                 d["output_status"], d["first_output_status"], d["retry_count"], d["llm_quotes"], d["verified_sources"],
                                 d["unverified_sources"], d["answer_chars"], d["seconds"], g.get("error"), d["answer"]])

    def cell(m, num, den=None):
        a = aggs[m]
        if den is None:
            return "—" if num(a) is None else str(num(a))
        return f"{num(a)}/{den(a)} ({pct(num(a), den(a))}%)" if den(a) else "—"

    def table(title, spec):
        lines = [f"## {title}", "", "| Metric | " + " | ".join(names[m] for m in present) + " |", "|---" * (len(present) + 1) + "|"]
        lines += [f"| {label} | " + " | ".join(cell(m, num, den) for m in present) + " |" for label, num, den in spec]
        return lines + [""]

    legal = [
        ("Overall score (0–100, mean; pre-registered pilot formula)", lambda a: a["overall_score_mean"], None),
        ("Fully correct (legal correctness 2/2)", lambda a: a["legal_correct_full"], lambda a: a["graded"]),
        ("Legal correctness mean (0–2)", lambda a: a["legal_correctness_mean_0_2"], None),
        ("Evidence fully supported", lambda a: a["evidence_fully_supported"], lambda a: a["graded"]),
        ("Hallucinations (answers with any)", lambda a: a["hallucinations"], lambda a: a["graded"]),
        ("Correct refusals (insufficient-evidence questions)", lambda a: a["abstention_correct_on_insufficient"], lambda a: a["insufficient_questions"]),
        ("Wrong refusals (answerable questions)", lambda a: a["wrong_refusals_on_answerable"], lambda a: a["answerable_questions"]),
        ("Grading failures", lambda a: a["grading_failures"], None),
    ]
    fmt = [
        ("Accurate citations (≥1 verified, 0 unverified)", lambda a: a["citation_accurate"], lambda a: a["questions"]),
        ("Verified citations (total)", lambda a: a["verified_citations_total"], None),
        ("Unverified citations (total)", lambda a: a["unverified_citations_total"], None),
        ("Evidence quotes matched / produced", lambda a: f"{a['evidence_quotes_matched_total']}/{a['citations_produced_total']}", None),
        ("Valid structured output (final)", lambda a: a["valid_output"], lambda a: a["questions"]),
        ("Valid on first attempt", lambda a: a["first_attempt_valid"], lambda a: a["questions"]),
        ("Malformed output (final)", lambda a: a["malformed_output"], lambda a: a["questions"]),
        ("Truncated output (final)", lambda a: a["truncated_output"], lambda a: a["questions"]),
        ("Failed (engine unavailable / error)", lambda a: a["failed_output"], lambda a: a["questions"]),
        ("Retries used (total)", lambda a: a["retries_total"], None),
        ("Answer text lost", lambda a: a["answer_text_lost"], lambda a: a["questions"]),
        ("Median generation latency (s)", lambda a: a["latency_median_s"], None),
        ("Mean answer length (chars)", lambda a: a["answer_chars_mean"], None),
        ("Median output tokens", lambda a: a["output_tokens_median"], None),
        ("Prompt identical to frozen benchmark prompt", lambda a: a["prompt_identical"], lambda a: a["questions"]),
    ]
    n_items = len(items)
    lines = ["# Answer-engine benchmark", "",
             f"Frozen held-out benchmark `{PROMPTS.name}` ({n_items} questions; {n_run} run). "
             "Each model answered from the identical stored RAG evidence and prompt through the app's engine path "
             "(src/engines.py): same validation, one-retry policy, citation mapping and citation verification. "
             f"Questions answered by every model from an identical evidence_id: {identical}/{n_run}.", ""]
    lines += table("LEGAL QUALITY (blind Claude rubric)", legal)
    lines += table("FORMAT / CITATION BEHAVIOUR (deterministic)", fmt)
    lines += ["## Reading this report", "",
              "- Legal quality and format are reported separately: better JSON or more verified citations are not, on their own, better legal answers.",
              "- Claude is graded against a reference written by Claude from the same evidence (pilot_v2 teacher), so its legal-quality scores are a ceiling, not an independent score.",
              "- LoRA Qwen is an experimental 30-example pilot adapter; its earlier pilot verdict was REGRESSION — INVESTIGATE.",
              "- The engine path retries once after MALFORMED/TRUNCATED output with a format reminder appended; the first-attempt status is reported alongside the final one.", ""]
    (out / "report.md").write_text("\n".join(lines))
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Benchmark the answer engines on the frozen held-out benchmark.")
    parser.add_argument("command", nargs="?", choices=["benchmark", "report"], default="benchmark")
    parser.add_argument("--models", default="claude,qwen,lora_qwen", help="Comma-separated engine keys.")
    parser.add_argument("--run", default="heldout_pilot_v2", help="Output folder under data/distill/engine_benchmark/.")
    parser.add_argument("--limit", type=int, default=None, help="Only the first N benchmark questions (smoke test).")
    parser.add_argument("--workers", type=int, default=4, help="Parallel Claude requests (local engines always run one at a time).")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    for model in models:
        engines.engine_spec(model)  # validates the key
    out = OUT_ROOT / args.run
    out.mkdir(parents=True, exist_ok=True)
    if args.command == "report":
        report(out, models)
        return

    status = {s["key"]: s for s in engines.engine_status()}
    unavailable = [m for m in models if not status[m]["available"]]
    if unavailable:
        # No fallback and no silent gaps: refuse to start rather than record a benchmark missing a model.
        sys.exit("Unavailable engines: " + "; ".join(f"{m}: {status[m]['detail']}" for m in unavailable))

    items = read_jsonl(PROMPTS)[: args.limit]
    # A record counts as done only if the engine produced output and the grader graded it. Records hit by an
    # infrastructure failure (API credit/outage, service down, grader error) are redone on the next run; the
    # report always uses the latest record per (model, question).
    done = ({(r["model"], r["key"]) for r in read_jsonl(out / "records.jsonl")
             if r["engine"]["output_status"] != "FAILED" and not r["rubric"].get("error")}
            if (out / "records.jsonl").exists() else set())
    jobs = [(m, i) for m in models for i in items if (m, f"{i['id']}|{i['source_run']}") not in done]
    (out / "run_config.json").write_text(json.dumps({"models": models, "benchmark": str(PROMPTS.relative_to(ROOT)), "limit": args.limit,
                                                      "engines": {m: status[m] for m in models},
                                                      "engine_max_retries": engines.settings.engine_max_retries}, indent=2, ensure_ascii=False))
    print(f"{len(jobs)} generations to run ({len(done)} already recorded)", flush=True)
    counter = {"n": 0}
    abort = threading.Event()
    fatal = ("credit balance is too low", "authentication_error", "invalid x-api-key")

    def work(job):
        model, item = job
        if abort.is_set():
            return
        record = run_one(model, item, out)
        errors = " ".join([record["rubric"].get("error") or ""] + [a.get("error") or "" for a in record["attempts"]])
        if any(marker in errors for marker in fatal):
            # Stop instead of filling the benchmark with infrastructure failures; rerun after fixing the account.
            abort.set()
            print(f"ABORTING: Anthropic API unusable ({errors.strip()[:200]}). Rerun the same command to resume.", flush=True)
        with _write_lock:
            counter["n"] += 1
            e = record["engine"]
            print(f"[{counter['n']}/{len(jobs)}] {model:9} {item['id']} {e['output_status']:9} retries={e['retry_count']} "
                  f"verified={e.get('verified_citations')}/{e.get('citation_count')} overall={record['overall']}", flush=True)

    local = [j for j in jobs if j[0] in LOCAL_ENGINES]
    remote = [j for j in jobs if j[0] not in LOCAL_ENGINES]
    with ThreadPoolExecutor(max_workers=args.workers + 1) as pool:
        futures = [pool.submit(lambda js=local: [work(j) for j in js])]
        futures += [pool.submit(work, j) for j in remote]
        for future in futures:
            future.result()
    report(out, models)


if __name__ == "__main__":
    main()
