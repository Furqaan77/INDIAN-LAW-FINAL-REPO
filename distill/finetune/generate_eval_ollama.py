"""
Baseline as the app runs local Qwen today: base qwen3:1.7b served by Ollama with thinking disabled and
JSON-schema-constrained output (the same request body as src/llm_provider.py OllamaProvider), on the same
stored evaluation prompts. Raw output is saved in the generate_eval.py format so score_eval.py scores it
identically.

Run with the app venv while Ollama is serving (and no MLX job is using the GPU):
    .venv/bin/python distill/finetune/generate_eval_ollama.py --prompts distill/finetune/data/eval_prompts_pilot_v2.jsonl
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from config import settings  # noqa: E402
from llm_provider import ANSWER_TOOL  # noqa: E402

LABEL = "ollama_base"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts", required=True)
    parser.add_argument("--max-tokens", type=int, default=1200)
    args = parser.parse_args()

    out = HERE / "eval" / f"outputs_{LABEL}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)["id"] + "|" + json.loads(l)["source_run"] for l in out.read_text().splitlines() if l.strip()} if out.exists() else set()
    items = [json.loads(l) for l in Path(args.prompts).read_text().splitlines() if l.strip()]
    items = [i for i in items if f"{i['id']}|{i['source_run']}" not in done]

    url = settings.ollama_base_url.rstrip("/") + "/api/chat"
    for index, item in enumerate(items, 1):
        body = {
            "model": settings.ollama_model, "stream": False, "think": False, "format": ANSWER_TOOL["input_schema"],
            "messages": [{"role": "system", "content": item["system"]}, {"role": "user", "content": item["user"]}],
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": args.max_tokens},
        }
        started = time.perf_counter()
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=600) as response:
            payload = json.load(response)
        elapsed = time.perf_counter() - started
        record = {"id": item["id"], "source_run": item["source_run"], "label": LABEL, "adapter": None,
                  "output": (payload.get("message") or {}).get("content", ""),
                  "prompt_tokens": payload.get("prompt_eval_count"), "output_tokens": payload.get("eval_count") or 0,
                  "seconds": round(elapsed, 2)}
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{index}/{len(items)}] {LABEL} {item['id']} {item['category']:22} {record['output_tokens']} tokens {elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
