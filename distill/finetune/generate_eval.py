"""
Generates answers from base or LoRA-fine-tuned Qwen (MLX) for every evaluation prompt.

Each prompt is the exact system prompt + user content the Claude teacher received (same excerpts, same
question, same dataset instruction), rendered with the model's chat template and thinking disabled.
Decoding is greedy. Output is appended per item, so an interrupted run resumes.

Run with the fine-tune venv:
    distill/finetune/.venv/bin/python distill/finetune/generate_eval.py --label base
    distill/finetune/.venv/bin/python distill/finetune/generate_eval.py --label lora --adapter distill/finetune/adapters/ft350
"""
import argparse
import json
import time
from pathlib import Path

from mlx_lm import generate, load

HERE = Path(__file__).resolve().parent
MODEL = HERE / "models" / "Qwen3-1.7B-4bit"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="Name of this model variant, e.g. base or lora.")
    parser.add_argument("--adapter", default=None, help="LoRA adapter directory (omit for the base model).")
    parser.add_argument("--prompts", default=str(HERE / "data" / "eval_prompts.jsonl"))
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    out = HERE / "eval" / f"outputs_{args.label}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)["id"] + "|" + json.loads(l)["source_run"] for l in out.read_text().splitlines() if l.strip()} if out.exists() else set()
    items = [json.loads(l) for l in Path(args.prompts).read_text().splitlines() if l.strip()]
    items = [i for i in items if f"{i['id']}|{i['source_run']}" not in done][: args.limit]

    model, tokenizer = load(str(MODEL), adapter_path=args.adapter)
    for index, item in enumerate(items, 1):
        messages = [{"role": "system", "content": item["system"]}, {"role": "user", "content": item["user"]}]
        prompt = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False, enable_thinking=False)
        prompt_tokens = len(tokenizer.encode(prompt))
        started = time.perf_counter()
        text = generate(model, tokenizer, prompt=prompt, max_tokens=args.max_tokens, verbose=False)
        elapsed = time.perf_counter() - started
        record = {"id": item["id"], "source_run": item["source_run"], "label": args.label, "adapter": args.adapter,
                  "output": text, "prompt_tokens": prompt_tokens, "output_tokens": len(tokenizer.encode(text)),
                  "seconds": round(elapsed, 2)}
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{index}/{len(items)}] {args.label} {item['id']} {item['category']:22} {record['output_tokens']} tokens {elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
