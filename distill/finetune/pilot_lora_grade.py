"""
LoRA distillation pilot — grades every model on the identical 50-question held-out benchmark.

Per model and question:
  * deterministic (score_eval.score_one): the app's citation parser, citation mapping and citation
    verification on the stored RAG evidence — valid structured output, citations produced / verified /
    unverified, evidence-quote match, inline markers, internal-markup leaks, abstention wording, length;
  * blind Claude rubric (grade_legal_answer), with the model identity hidden:
      legal_correctness 0-2  (against the excerpts and the Claude teacher reference answer)
      evidence_support  0-2  (every claim traceable to the excerpts)
      hallucination     bool (any fact, rule or authority not in the excerpts)
      structure         0-2  (direct answer first, organised, claims marked with citations)
      abstention_correct bool (insufficient-evidence questions: says so; answerable ones: does not wrongly refuse)

Pre-registered scoring:
  overall (0-100) = mean of [correctness/2, support/2, structure/2, 1-hallucination,
                             valid structured output, citation accuracy (>=1 verified citation and 0 unverified)]
  LoRA vs Base per question: IMPROVED if overall +10 or more, REGRESSED if -10 or less, SAME otherwise,
                             UNCLEAR if either grade failed.

Results are cached in grades.jsonl (resumable). Run with the app venv:
    .venv/bin/python distill/finetune/pilot_lora_grade.py --models base lora ollama_base claude
"""
import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "distill"))

import score_eval  # noqa: E402  (imports generate_teacher, rag_chain)
from common import call_claude_tool, read_jsonl  # noqa: E402

PROMPTS = HERE / "data" / "eval_prompts_pilot_v2.jsonl"
OUT = ROOT / "data" / "distill" / "pilot_lora"
GRADES = OUT / "grades.jsonl"
_lock = threading.Lock()

RUBRIC_TOOL = {
    "name": "grade_legal_answer",
    "description": "Grade one answer to an Indian legal research question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "legal_correctness": {"type": "integer", "minimum": 0, "maximum": 2,
                                  "description": "2 = correct and complete on the legal point; 1 = partly correct or incomplete; 0 = wrong, missing or does not answer."},
            "evidence_support": {"type": "integer", "minimum": 0, "maximum": 2,
                                 "description": "2 = every legal claim is stated in the excerpts; 1 = mostly; 0 = largely unsupported."},
            "hallucination": {"type": "boolean", "description": "True if any fact, rule, figure, section, case or citation is not in the excerpts."},
            "unsupported_claims": {"type": "array", "items": {"type": "string"}},
            "structure": {"type": "integer", "minimum": 0, "maximum": 2,
                          "description": "2 = answers directly first, organised, claims marked with citation markers; 1 = usable but weak; 0 = disorganised, repetitive or unusable."},
            "abstention_correct": {"type": "boolean",
                                   "description": "If the question cannot be answered from the excerpts: true only if the answer says so. If it can: true only if the answer does not wrongly refuse."},
            "notes": {"type": "string"},
        },
        "required": ["legal_correctness", "evidence_support", "hallucination", "unsupported_claims", "structure", "abstention_correct", "notes"],
    },
}

RUBRIC_SYSTEM = """You are a strict grader of answers to Indian legal research questions. You are NOT told which system wrote the answer.
Judge only against the excerpts provided and the reference answer (a verified answer written from the same excerpts). Do not use outside legal knowledge to add or excuse claims.
The reference is a guide to what a correct answer covers; an answer may be worded differently and still be fully correct, or may correctly give less detail."""


def claude_outputs(items):
    records = {r["id"]: r for r in read_jsonl(ROOT / "data" / "distill" / "pilot_v2" / "teacher_records.jsonl")}
    outputs = []
    for item in items:
        record = records[item["id"]]
        text = json.dumps({"citations": record["target"]["citations"], "answer": record["target"]["answer"]}, ensure_ascii=False)
        outputs.append({"id": item["id"], "source_run": item["source_run"], "label": "claude", "output": text,
                        "output_tokens": 0, "seconds": (record["teacher"].get("timings") or {}).get("generation_s") or 0.0})
    return outputs


def load_outputs(label, items):
    if label == "claude":
        return claude_outputs(items)
    return [json.loads(l) for l in (HERE / "eval" / f"outputs_{label}.jsonl").read_text().splitlines() if l.strip()]


def rubric(item, row):
    excerpts = "\n\n".join(f"--- Excerpt {i} ({e['source_type']}): {e['title']} ---\n{e['text']}" for i, e in enumerate(row["excerpts"], 1))
    prompt = (f"Excerpts:\n{excerpts}\n\nQuestion: {item['question']}\n"
              f"Question type: {'the excerpts were judged NOT to answer this question' if item['expected'] == 'insufficient' else 'answerable from the excerpts'}\n\n"
              f"Reference answer:\n{item['reference']['answer']}\n\nAnswer to grade:\n{row['answer'] or '(empty)'}")
    try:
        return {**call_claude_tool(RUBRIC_TOOL, RUBRIC_SYSTEM, prompt, max_tokens=900), "error": None}
    except Exception as error:
        return {"error": str(error)}


def overall(row, grade):
    if grade.get("error"):
        return None
    citation_accuracy = 1.0 if row["verified_sources"] > 0 and row["unverified_sources"] == 0 else 0.0
    parts = [grade["legal_correctness"] / 2, grade["evidence_support"] / 2, grade["structure"] / 2,
             0.0 if grade["hallucination"] else 1.0, 1.0 if row["json_ok"] else 0.0, citation_accuracy]
    return round(100 * sum(parts) / len(parts), 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--rescore", action="store_true",
                        help="Recompute deterministic metrics and overall scores for existing grades (answers unchanged, no Claude calls).")
    args = parser.parse_args()

    items = {f"{i['id']}|{i['source_run']}": i for i in read_jsonl(PROMPTS)}
    OUT.mkdir(parents=True, exist_ok=True)
    if args.rescore:
        latest = {}
        for grade in read_jsonl(GRADES):
            latest[(grade["model"], grade["key"])] = grade
        outputs = {label: {f"{o['id']}|{o['source_run']}": o for o in load_outputs(label, list(items.values()))}
                   for label in {model for model, _ in latest}}
        rescored = []
        for (label, key), grade in latest.items():
            row = score_eval.score_one(items[key], outputs[label][key], grade_with_claude=False)
            rescored.append({**grade, "deterministic": {k: v for k, v in row.items() if k != "excerpts"},
                             "overall": overall(row, grade["rubric"])})
        GRADES.write_text("".join(json.dumps(g, ensure_ascii=False) + "\n" for g in rescored))
        print(f"rescored {len(rescored)} grades")
        return
    done = {(g["model"], g["key"]) for g in read_jsonl(GRADES)}
    jobs = []
    for label in args.models:
        for generation in load_outputs(label, list(items.values())):
            key = f"{generation['id']}|{generation['source_run']}"
            if key in items and (label, key) not in done:
                jobs.append((label, key, generation))
    print(f"grading {len(jobs)} answers", flush=True)

    def work(job):
        label, key, generation = job
        item = items[key]
        row = score_eval.score_one(item, generation, grade_with_claude=False)
        grade = rubric(item, row)
        result = {"model": label, "key": key, "id": item["id"], "category": item["category"], "expected": item["expected"],
                  "question": item["question"], "deterministic": {k: v for k, v in row.items() if k != "excerpts"},
                  "rubric": grade, "overall": overall(row, grade), "latency_s": generation.get("seconds")}
        with _lock:
            with GRADES.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        return label, item["id"], result["overall"]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for index, (label, qid, score) in enumerate(pool.map(work, jobs), 1):
            print(f"[{index}/{len(jobs)}] {label:12} {qid} overall={score}", flush=True)


if __name__ == "__main__":
    main()
