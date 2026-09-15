"""
Builds LoRA fine-tuning data (MLX-LM chat format) and an evaluation prompt set from graded teacher runs.

Training examples come ONLY from VERIFIED teacher records in the run's leakage-safe splits:
  input  = the exact system prompt and user content Claude received (question + retrieved excerpts +
           dataset answer instruction);
  target = Claude's structured output, {"citations": [{"doc_id", "evidence_quote"}], "answer": ...},
           in the same shape the app's answer tool uses, so the fine-tuned model can be dropped into
           the existing citation mapping and verification.

Evaluation prompts (never trained on): the run's test split plus every question of the extra runs
(e.g. pilot_v2), with the reference teacher answer and the retrieved evidence kept for scoring.

Run with the fine-tune venv (needs the model tokenizer for length filtering):
    distill/finetune/.venv/bin/python distill/finetune/build_sft_data.py --run ft350 --eval-extra pilot_v2
"""
import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "distill"
OUT = Path(__file__).resolve().parent / "data"
MODEL = Path(__file__).resolve().parent / "models" / "Qwen3-1.7B-4bit"


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def target_json(record):
    target = record["target"]
    return json.dumps({"citations": target["citations"], "answer": target["answer"]}, ensure_ascii=False)


def chat_example(record):
    prompt = record["teacher_prompt"]
    return {"messages": [
        {"role": "system", "content": prompt["system_prompt"]},
        {"role": "user", "content": prompt["user_content"]},
        {"role": "assistant", "content": target_json(record)},
    ]}


def eval_item(record, source_run, split):
    prompt = record["teacher_prompt"]
    return {
        "id": record["id"], "source_run": source_run, "split": split, "category": record["category"],
        "expected": record["expected"], "question": record["question"],
        "system": prompt["system_prompt"], "user": prompt["user_content"],
        "reference": {"answer": record.get("teacher_answer"), "quality_status": record["quality_status"],
                      "answer_type": record["answer_type"], "verified_citations": record["verified_citations"]},
        "retrieved_context": record["retrieved_context"],
        "question_record": record.get("question_record") or {"expected": record["expected"]},
        "seed": record["seed"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--eval-extra", nargs="*", default=[])
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    out = Path(args.out)

    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL))

    def length(example):
        # Render to text first: newer tokenizers return an encoding object, not a token list, when tokenize=True.
        text = tokenizer.apply_chat_template(example["messages"], tokenize=False)
        return len(tokenizer.encode(text))

    run = DATA / args.run
    out.mkdir(parents=True, exist_ok=True)
    report = {"run": args.run, "max_tokens": args.max_tokens}
    for split, name in (("train", "train"), ("validation", "valid"), ("test", "test")):
        records = read_jsonl(run / f"{split}.jsonl")
        examples, dropped, lengths = [], 0, []
        for record in records:
            example = chat_example(record)
            n = length(example)
            if n > args.max_tokens:
                dropped += 1
                continue
            examples.append(example)
            lengths.append(n)
        (out /f"{name}.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in examples), encoding="utf-8")
        report[name] = {"examples": len(examples), "dropped_over_length": dropped,
                        "tokens_mean": round(sum(lengths) / len(lengths)) if lengths else None, "tokens_max": max(lengths) if lengths else None,
                        "categories": dict(Counter(r["category"] for r in records))}

    items = [eval_item(r, args.run, "test") for r in read_jsonl(run / "test.jsonl")]
    for extra in args.eval_extra:
        records = {r["id"]: r for r in read_jsonl(DATA / extra / "teacher_records.jsonl")}
        items += [eval_item(r, extra, "all") for r in records.values()]
    trained_questions = {json.loads(line)["messages"][1]["content"] for line in (out /"train.jsonl").read_text().splitlines()}
    leaked = sum(1 for item in items if item["user"] in trained_questions)
    (out /"eval_prompts.jsonl").write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    report["eval"] = {"items": len(items), "by_run": dict(Counter(i["source_run"] for i in items)),
                      "prompts_also_in_train": leaked}
    (out /"build_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
