"""
POST-HOC DIAGNOSTIC (not part of the pre-registered benchmark).

The LoRA student frequently emits `{"citations": [...], {"answer": "..."}` — an extra "{" before the answer
key — so strict JSON parsing fails and the answer text is lost. This script applies one deterministic,
content-preserving repair (remove that stray brace; drop a trailing extra "}" if the object then has one too
many) and writes outputs_lora_repaired.jsonl. Grading the repaired outputs separates the format defect from the
legal content of the answers. The primary result remains the unrepaired LoRA output.

Usage:
    python3 distill/finetune/repair_lora_outputs.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "eval" / "outputs_lora.jsonl"
TARGET = HERE / "eval" / "outputs_lora_repaired.jsonl"
STRAY_BRACE = re.compile(r"\]\s*,\s*\{\s*\"answer\"")


def strictly_valid(text):
    try:
        obj = json.loads(text[text.find("{"): text.rfind("}") + 1])
        return isinstance(obj, dict) and isinstance(obj.get("citations"), list) and bool(str(obj.get("answer") or "").strip())
    except ValueError:
        return False


def main():
    rows = [json.loads(line) for line in SOURCE.read_text().splitlines() if line.strip()]
    stats = {"outputs": len(rows), "valid_before": 0, "stray_brace_found": 0, "valid_after": 0}
    with TARGET.open("w", encoding="utf-8") as handle:
        for row in rows:
            text = row["output"]
            stats["valid_before"] += strictly_valid(text)
            repaired = text
            if STRAY_BRACE.search(text):
                stats["stray_brace_found"] += 1
                repaired = STRAY_BRACE.sub('], "answer"', text, count=1)
                if not strictly_valid(repaired) and repaired.rstrip().endswith("}}"):
                    repaired = repaired.rstrip()[:-1]
            stats["valid_after"] += strictly_valid(repaired)
            handle.write(json.dumps({**row, "label": "lora_repaired", "output": repaired, "repaired": repaired != text}, ensure_ascii=False) + "\n")
    print(json.dumps(stats, indent=2))
    (HERE / "eval" / "repair_stats.json").write_text(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
