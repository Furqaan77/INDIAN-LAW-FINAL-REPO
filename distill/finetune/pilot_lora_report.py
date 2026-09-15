"""
LoRA distillation pilot — builds the benchmark report from graded results (data/distill/pilot_lora/grades.jsonl).

Writes to data/distill/pilot_lora/: benchmark_results.json/.csv, per_question_comparison.csv, summary.md,
demo_examples.md, benchmark_chart.svg, training_config.json, model_metadata.json, README.md.

Run with the app venv after pilot_lora_grade.py:
    .venv/bin/python distill/finetune/pilot_lora_report.py
"""
import csv
import json
import math
import random
import re
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "distill" / "pilot_lora"
ADAPTER = ROOT / "artifacts" / "lora_demo_qwen3_1.7b"
CONFIG = ROOT / "distill" / "finetune" / "pilot_lora_config.yaml"
PROMPTS = ROOT / "distill" / "finetune" / "data" / "eval_prompts_pilot_v2.jsonl"
MODELS = {
    "base": "Base Qwen3-1.7B + RAG",
    "lora": "LoRA Qwen3-1.7B + RAG",
    "claude": "Claude + RAG",
    "ollama_base": "Base Qwen3-1.7B + RAG (app runtime: Ollama, JSON-constrained)",
    "lora_repaired": "LoRA Qwen3-1.7B + RAG, post-hoc JSON repair (diagnostic only)",
}
THRESHOLD = 10.0


def load():
    grades = {}
    for line in (OUT / "grades.jsonl").read_text().splitlines():
        if line.strip():
            g = json.loads(line)
            grades[(g["model"], g["id"])] = g
    return grades


def pct(n, d):
    return round(100 * n / d, 1) if d else None


def aggregate(rows):
    graded = [r for r in rows if not r["rubric"].get("error")]
    n, ng = len(rows), len(graded)
    insufficient = [r for r in graded if r["expected"] == "insufficient"]
    latencies = [r["latency_s"] for r in rows if r.get("latency_s")]
    return {
        "questions": n, "graded": ng,
        "overall_score_mean": round(statistics.mean(r["overall"] for r in graded), 1) if graded else None,
        "legal_correct_full": sum(1 for r in graded if r["rubric"]["legal_correctness"] == 2),
        "legal_correctness_mean_0_2": round(statistics.mean(r["rubric"]["legal_correctness"] for r in graded), 2) if graded else None,
        "evidence_fully_supported": sum(1 for r in graded if r["rubric"]["evidence_support"] == 2),
        "evidence_support_mean_0_2": round(statistics.mean(r["rubric"]["evidence_support"] for r in graded), 2) if graded else None,
        "citation_accurate": sum(1 for r in rows if r["deterministic"]["verified_sources"] > 0 and r["deterministic"]["unverified_sources"] == 0),
        "answers_with_verified_citation": sum(1 for r in rows if r["deterministic"]["verified_sources"] > 0),
        "verified_citations_total": sum(r["deterministic"]["verified_sources"] for r in rows),
        "unverified_citations_total": sum(r["deterministic"]["unverified_sources"] for r in rows),
        "citations_produced_total": sum(r["deterministic"]["llm_quotes"] for r in rows),
        "evidence_quotes_matched_total": sum(r["deterministic"]["llm_quotes"] - r["deterministic"]["unmatched_quotes"] for r in rows),
        "hallucinations": sum(1 for r in graded if r["rubric"]["hallucination"]),
        "valid_structured_output": sum(1 for r in rows if r["deterministic"]["json_ok"]),
        "structure_mean_0_2": round(statistics.mean(r["rubric"]["structure"] for r in graded), 2) if graded else None,
        "abstention_correct_all": sum(1 for r in graded if r["rubric"]["abstention_correct"]),
        "insufficient_questions": len(insufficient),
        "abstention_correct_on_insufficient": sum(1 for r in insufficient if r["rubric"]["abstention_correct"]),
        "internal_markup_leaks": sum(1 for r in rows if r["deterministic"]["internal_leak"]),
        "answer_text_lost": sum(1 for r in rows if r["deterministic"].get("answer_lost")),
        "truncated_outputs": sum(1 for r in rows if r["deterministic"]["truncated"]),
        "answer_chars_mean": round(statistics.mean(r["deterministic"]["answer_chars"] for r in rows)) if rows else None,
        "latency_median_s": round(statistics.median(latencies), 2) if latencies else None,
        "grading_failures": n - ng,
    }


def classify(base, lora):
    if base["overall"] is None or lora["overall"] is None:
        return "UNCLEAR"
    diff = lora["overall"] - base["overall"]
    return "IMPROVED" if diff >= THRESHOLD else "REGRESSED" if diff <= -THRESHOLD else "SAME"


def sign_test(improved, regressed):
    n = improved + regressed
    if n == 0:
        return None
    k = min(improved, regressed)
    return round(min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n), 4)


def bootstrap_ci(diffs, seed=42, reps=5000):
    if not diffs:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choice(diffs) for _ in diffs) for _ in range(reps))
    return [round(means[int(0.025 * reps)], 1), round(means[int(0.975 * reps)], 1)]


def svg_chart(aggs, keys):
    metrics = [("Overall score", lambda a: a["overall_score_mean"]),
               ("Legal correct (full)", lambda a: pct(a["legal_correct_full"], a["graded"])),
               ("Evidence fully supported", lambda a: pct(a["evidence_fully_supported"], a["graded"])),
               ("Citation accuracy", lambda a: pct(a["citation_accurate"], a["questions"])),
               ("Valid structured output", lambda a: pct(a["valid_structured_output"], a["questions"])),
               ("No hallucination", lambda a: pct(a["graded"] - a["hallucinations"], a["graded"]))]
    colors = {"base": "#8a93a6", "lora": "#2f6fd6", "claude": "#1f9d6b"}
    width, row_h, left, plot_w = 760, 70, 210, 480
    height = 60 + row_h * len(metrics)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="Helvetica, Arial, sans-serif" font-size="12">',
             f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
             '<text x="16" y="24" font-size="15" font-weight="bold" fill="#1b1f2a">IndianLawGPT LoRA pilot — measured results (50 held-out questions, %)</text>']
    for index, key in enumerate(keys):
        parts.append(f'<rect x="{left + index * 170}" y="36" width="12" height="12" fill="{colors[key]}"/><text x="{left + index * 170 + 18}" y="46" fill="#1b1f2a">{MODELS[key]}</text>')
    for m, (label, fn) in enumerate(metrics):
        y0 = 60 + m * row_h
        parts.append(f'<text x="16" y="{y0 + 30}" fill="#1b1f2a">{label}</text>')
        for index, key in enumerate(keys):
            value = fn(aggs[key]) or 0
            y = y0 + 8 + index * 18
            parts.append(f'<rect x="{left}" y="{y}" width="{plot_w * value / 100:.1f}" height="14" fill="{colors[key]}"/>')
            parts.append(f'<text x="{left + plot_w * value / 100 + 6:.1f}" y="{y + 11}" fill="#1b1f2a">{value}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def training_facts():
    log = (ADAPTER / "training.log").read_text() if (ADAPTER / "training.log").exists() else ""
    train = re.findall(r"Iter (\d+): Train loss ([\d.]+).*?Peak mem ([\d.]+) GB", log)
    val = re.findall(r"Iter (\d+): Val loss ([\d.]+)", log)
    trainable = re.search(r"Trainable parameters: ([\d.]+)% \(([\d.]+)M/([\d.]+)M\)", log)
    return {"train_loss": [{"iter": int(i), "loss": float(l)} for i, l, _ in train],
            "val_loss": [{"iter": int(i), "loss": float(l)} for i, l in val],
            "peak_memory_gb": max((float(p) for *_, p in train), default=None),
            "trainable_parameters": {"percent": float(trainable.group(1)), "millions": float(trainable.group(2)), "total_millions": float(trainable.group(3))} if trainable else None}


def short(text, limit=900):
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + " …"


def main():
    grades = load()
    items = [json.loads(l) for l in PROMPTS.read_text().splitlines() if l.strip()]
    present = [k for k in MODELS if any((k, i["id"]) in grades for i in items)]
    rows = {k: [grades[(k, i["id"])] for i in items if (k, i["id"]) in grades] for k in present}
    aggs = {k: aggregate(v) for k, v in rows.items()}

    comparison, diffs, counts = [], [], defaultdict(int)
    flags = defaultdict(int)
    for item in items:
        b, l, c = grades.get(("base", item["id"])), grades.get(("lora", item["id"])), grades.get(("claude", item["id"]))
        if not (b and l):
            continue
        verdict = classify(b, l)
        counts[verdict] += 1
        if verdict != "UNCLEAR":
            diffs.append(l["overall"] - b["overall"])
        bd, ld = b["deterministic"], l["deterministic"]
        br, lr = b["rubric"], l["rubric"]
        f = {
            "citation_improved": bd["verified_sources"] == 0 and ld["verified_sources"] > 0,
            "citation_regressed": bd["verified_sources"] > 0 and ld["verified_sources"] == 0,
            "correctness_improved": not br.get("error") and not lr.get("error") and lr["legal_correctness"] > br["legal_correctness"],
            "correctness_regressed": not br.get("error") and not lr.get("error") and lr["legal_correctness"] < br["legal_correctness"],
            "formatting_improved": (not bd["json_ok"] and ld["json_ok"]),
            "formatting_regressed": (bd["json_ok"] and not ld["json_ok"]),
            "hallucination_reduced": not br.get("error") and not lr.get("error") and br["hallucination"] and not lr["hallucination"],
            "hallucination_introduced": not br.get("error") and not lr.get("error") and not br["hallucination"] and lr["hallucination"],
            "abstention_improved": item["expected"] == "insufficient" and not br.get("error") and not lr.get("error") and not br["abstention_correct"] and lr["abstention_correct"],
        }
        for key, value in f.items():
            flags[key] += bool(value)
        comparison.append({
            "question_id": item["id"], "category": item["category"], "expected": item["expected"], "question": item["question"],
            "base_overall": b["overall"], "lora_overall": l["overall"], "claude_overall": c["overall"] if c else None,
            "ollama_base_overall": grades[("ollama_base", item["id"])]["overall"] if ("ollama_base", item["id"]) in grades else None,
            "lora_vs_base": verdict, "overall_diff": None if verdict == "UNCLEAR" else round(l["overall"] - b["overall"], 1),
            "base_correctness": br.get("legal_correctness"), "lora_correctness": lr.get("legal_correctness"), "claude_correctness": (c or {}).get("rubric", {}).get("legal_correctness"),
            "base_verified_citations": bd["verified_sources"], "lora_verified_citations": ld["verified_sources"],
            "base_valid_json": bd["json_ok"], "lora_valid_json": ld["json_ok"],
            "base_hallucination": br.get("hallucination"), "lora_hallucination": lr.get("hallucination"),
            **{k: bool(v) for k, v in f.items()},
        })

    improved, regressed = counts["IMPROVED"], counts["REGRESSED"]
    stats = {"improved": improved, "same": counts["SAME"], "regressed": regressed, "unclear": counts["UNCLEAR"],
             "net_improvement": improved - regressed, "classification_threshold_points": THRESHOLD,
             "mean_overall_diff": round(statistics.mean(diffs), 1) if diffs else None,
             "bootstrap_95ci_mean_overall_diff": bootstrap_ci(diffs), "sign_test_p_value": sign_test(improved, regressed),
             **dict(flags)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "benchmark_results.json").write_text(json.dumps({"models": MODELS, "aggregates": aggs, "lora_vs_base": stats,
                                                             "per_question": comparison, "benchmark_ids": [i["id"] for i in items]}, indent=2, ensure_ascii=False))
    with (OUT / "benchmark_results.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["model", "question_id", "category", "expected", "overall", "legal_correctness", "evidence_support", "hallucination",
                         "structure", "abstention_correct", "valid_json", "citations_produced", "verified_citations", "unverified_citations",
                         "verified_doc_ids", "retrieved_doc_ids", "answer_chars", "latency_s", "grading_error", "answer"])
        for key in present:
            for r in rows[key]:
                d, g = r["deterministic"], r["rubric"]
                writer.writerow([key, r["id"], r["category"], r["expected"], r["overall"], g.get("legal_correctness"), g.get("evidence_support"),
                                 g.get("hallucination"), g.get("structure"), g.get("abstention_correct"), d["json_ok"], d["llm_quotes"],
                                 d["verified_sources"], d["unverified_sources"], ";".join(d["verified_doc_ids"]), ";".join(d["retrieved_doc_ids"]),
                                 d["answer_chars"], r.get("latency_s"), g.get("error"), d["answer"]])
    if comparison:
        with (OUT / "per_question_comparison.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(comparison[0].keys()))
            writer.writeheader()
            writer.writerows(comparison)

    chart_keys = [k for k in ("base", "lora", "claude") if k in aggs]
    (OUT / "benchmark_chart.svg").write_text(svg_chart(aggs, chart_keys))
    facts = training_facts()
    config_text = CONFIG.read_text()
    (OUT / "training_config.json").write_text(json.dumps({"config_file": str(CONFIG.relative_to(ROOT)), "config_yaml": config_text, **facts}, indent=2))
    (OUT / "model_metadata.json").write_text(json.dumps({
        "student_base_model": "mlx-community/Qwen3-1.7B-4bit (Qwen/Qwen3-1.7B, 4-bit MLX quantization)",
        "student_runtime": "MLX-LM 0.31.3 / MLX 0.32.2, Apple M3, 8 GB; greedy decoding, thinking disabled, max 1200 new tokens",
        "adapter": str(ADAPTER.relative_to(ROOT)), "teacher": "Claude (claude-sonnet-5) via IndianLawGPT answer_question()",
        "app_runtime_baseline": "Ollama qwen3:1.7b (Q4_K_M), think=false, JSON-schema-constrained output (src/llm_provider.py request body)",
        "grader": "Claude (claude-sonnet-5), blind rubric (distill/finetune/pilot_lora_grade.py)",
        "git_commit": "1317809 (distillation and retrieval changes since this commit are uncommitted in the working tree)",
        "trainable_parameters": facts["trainable_parameters"],
    }, indent=2))

    def cell(key, num, den=None, fmt="{}"):
        if key not in aggs:
            return "—"
        a = aggs[key]
        n = num(a)
        if den is None:
            return fmt.format(n)
        d = den(a)
        return f"{n}/{d} ({pct(n, d)}%)"

    def change(num, den=None, unit="pp"):
        if "base" not in aggs or "lora" not in aggs:
            return "—"
        b, l = aggs["base"], aggs["lora"]
        if den is None:
            delta = round(num(l) - num(b), 2)
            return f"{delta:+}"
        return f"{num(l) - num(b):+} questions, {round(pct(num(l), den(l)) - pct(num(b), den(b)), 1):+} pp"

    table = [
        ("Overall score (0–100, mean)", lambda a: a["overall_score_mean"], None),
        ("Legal correctness — fully correct", lambda a: a["legal_correct_full"], lambda a: a["graded"]),
        ("Legal correctness — mean (0–2)", lambda a: a["legal_correctness_mean_0_2"], None),
        ("Evidence support — fully supported", lambda a: a["evidence_fully_supported"], lambda a: a["graded"]),
        ("Citation accuracy (≥1 verified, 0 unverified)", lambda a: a["citation_accurate"], lambda a: a["questions"]),
        ("Verified citations (total)", lambda a: a["verified_citations_total"], None),
        ("Unverified citations (total)", lambda a: a["unverified_citations_total"], None),
        ("Hallucination (answers with any)", lambda a: a["hallucinations"], lambda a: a["graded"]),
        ("Valid structured output (strict JSON)", lambda a: a["valid_structured_output"], lambda a: a["questions"]),
        ("Answer text lost (malformed output)", lambda a: a["answer_text_lost"], lambda a: a["questions"]),
        ("Abstention correct — insufficient questions", lambda a: a["abstention_correct_on_insufficient"], lambda a: a["insufficient_questions"]),
        ("Abstention correct — all questions", lambda a: a["abstention_correct_all"], lambda a: a["graded"]),
        ("Structure (0–2, mean)", lambda a: a["structure_mean_0_2"], None),
        ("Average answer length (chars)", lambda a: a["answer_chars_mean"], None),
        ("Median latency (s)", lambda a: a["latency_median_s"], None),
    ]
    lines = ["# IndianLawGPT — Qwen3-1.7B LoRA Distillation Pilot", "", "## Main benchmark", "",
             f"50 held-out questions (benchmark `pilot_v2`); identical question, retrieved evidence, prompt, citation parser, citation mapping and verifier for every model. Only the answer model changes.", "",
             "| Metric | Base Qwen + RAG | LoRA Qwen + RAG | Claude + RAG | LoRA change | Base Qwen (app runtime, Ollama JSON) |", "|---|---|---|---|---|---|"]
    for label, num, den in table:
        lines.append(f"| {label} | {cell('base', num, den)} | {cell('lora', num, den)} | {cell('claude', num, den)} | {change(num, den)} | {cell('ollama_base', num, den)} |")
    base_o, lora_o = aggs.get("base", {}).get("overall_score_mean"), aggs.get("lora", {}).get("overall_score_mean")
    lines += ["", "## Before vs after", "", f"- Base Qwen: **{base_o}**", f"- LoRA Qwen: **{lora_o}**",
              f"- Change: **{round(lora_o - base_o, 1):+} points** (overall score, 0–100)" if base_o is not None and lora_o is not None else "- Change: —",
              "", "## LoRA vs Base per question", "",
              f"Rule (pre-registered): IMPROVED if overall +{THRESHOLD:g} or more, REGRESSED if −{THRESHOLD:g} or less, otherwise SAME; UNCLEAR if grading failed.", "",
              "| Improved | Same | Regressed | Unclear | Net | Mean diff | Bootstrap 95% CI | Sign test p |", "|---|---|---|---|---|---|---|---|",
              f"| {improved} | {counts['SAME']} | {regressed} | {counts['UNCLEAR']} | {improved - regressed:+} | {stats['mean_overall_diff']} | {stats['bootstrap_95ci_mean_overall_diff']} | {stats['sign_test_p_value']} |",
              "", "| Change type (question counts) | Improved | Regressed |", "|---|---|---|",
              f"| Citations (0 → ≥1 verified) | {flags['citation_improved']} | {flags['citation_regressed']} |",
              f"| Legal correctness score | {flags['correctness_improved']} | {flags['correctness_regressed']} |",
              f"| Valid structured output | {flags['formatting_improved']} | {flags['formatting_regressed']} |",
              f"| Hallucination | {flags['hallucination_reduced']} reduced | {flags['hallucination_introduced']} introduced |",
              f"| Abstention on insufficient questions | {flags['abstention_improved']} | — |",
              "", "## Per-question result", "", "| Question ID | Category | Base | LoRA | Claude | LoRA vs Base |", "|---|---|---|---|---|---|"]
    for row in comparison:
        lines.append(f"| {row['question_id']} | {row['category']} | {row['base_overall']} | {row['lora_overall']} | {row['claude_overall']} | {row['lora_vs_base']} |")
    if "lora_repaired" in aggs:
        repair = json.loads((ROOT / "distill" / "finetune" / "eval" / "repair_stats.json").read_text())
        lines += ["", "## Post-hoc diagnostic — LoRA output with the stray-brace JSON defect repaired", "",
                  "Not part of the pre-registered benchmark. The LoRA student often writes `{\"citations\": [...], {\"answer\": ...}` (an extra `{`), "
                  f"so the answer text is lost when parsed. One deterministic repair (remove the stray brace) was applied to {repair['stray_brace_found']} of "
                  f"{repair['outputs']} outputs (strictly valid JSON: {repair['valid_before']} before, {repair['valid_after']} after), then re-graded blind. "
                  "This separates the format defect from answer content.", "",
                  "| Metric | Base Qwen + RAG | LoRA (as generated) | LoRA (JSON repaired) | Claude + RAG |", "|---|---|---|---|---|"]
        for label, num, den in table:
            lines.append(f"| {label} | {cell('base', num, den)} | {cell('lora', num, den)} | {cell('lora_repaired', num, den)} | {cell('claude', num, den)} |")
    lines += ["", "## Statistical caution", "",
              "This is a 30-example, 50-question pilot. Any difference here is an early signal, not proof that distillation works; "
              "it needs confirmation on a larger held-out benchmark with more training data. Claude's own scores are graded against "
              "a reference written by Claude from the same evidence, so they are a ceiling reference, not an independent competitor score."]
    (OUT / "summary.md").write_text("\n".join(lines) + "\n")

    ranked = sorted([r for r in comparison if r["lora_vs_base"] == "IMPROVED"], key=lambda r: (-r["overall_diff"], -(r["lora_correctness"] or 0)))
    worst = sorted([r for r in comparison if r["lora_vs_base"] == "REGRESSED"], key=lambda r: r["overall_diff"])
    demo = ["# LoRA pilot — demo examples", "", "Selected by overall-score difference (LoRA − Base) on the held-out benchmark; regressions included.", ""]
    for title, group in (("Largest improvements", ranked[:5]), ("Regressions", worst[:3])):
        demo += [f"## {title}", ""]
        if not group:
            demo += ["_None._", ""]
        for r in group:
            b, l, c = grades[("base", r["question_id"])], grades[("lora", r["question_id"])], grades.get(("claude", r["question_id"]))
            demo += [f"### {r['question_id']} — {r['category']} (Base {r['base_overall']} → LoRA {r['lora_overall']}, Claude {r['claude_overall']})", "",
                     f"**Question:** {r['question']}", "",
                     f"**Retrieved evidence:** {', '.join(l['deterministic']['retrieved_doc_ids'])}", "",
                     f"**Citations verified:** Base {b['deterministic']['verified_doc_ids'] or 'none'} · LoRA {l['deterministic']['verified_doc_ids'] or 'none'} · Claude {c['deterministic']['verified_doc_ids'] if c else '—'}", "",
                     f"**Scores (correctness / support / hallucination / valid JSON):** Base {b['rubric'].get('legal_correctness')}/{b['rubric'].get('evidence_support')}/{b['rubric'].get('hallucination')}/{b['deterministic']['json_ok']} · "
                     f"LoRA {l['rubric'].get('legal_correctness')}/{l['rubric'].get('evidence_support')}/{l['rubric'].get('hallucination')}/{l['deterministic']['json_ok']}", "",
                     "**Base Qwen:**", "", "> " + short(b["deterministic"]["answer"]).replace("\n", "\n> "), "",
                     "**LoRA Qwen:**", "", "> " + short(l["deterministic"]["answer"]).replace("\n", "\n> "), "",
                     "**Claude:**", "", "> " + short(c["deterministic"]["answer"] if c else "").replace("\n", "\n> "), "",
                     f"**Grader notes (LoRA):** {short(l['rubric'].get('notes'), 500)}", "",
                     f"**Grader notes (Base):** {short(b['rubric'].get('notes'), 500)}", ""]
    (OUT / "demo_examples.md").write_text("\n".join(demo) + "\n")

    manifest = json.loads((OUT / "train_30_manifest.json").read_text())
    readme = [
        "# IndianLawGPT — Qwen3-1.7B LoRA Distillation Pilot", "",
        "Small, controlled experiment: can 30 verified Claude + IndianLawGPT RAG teacher answers teach Qwen3-1.7B useful legal-answering behaviour?", "",
        "## Experiment", "",
        "| | |", "|---|---|",
        "| Teacher | Claude (claude-sonnet-5) + IndianLawGPT RAG |",
        "| Student | Qwen3-1.7B, 4-bit MLX (mlx-community/Qwen3-1.7B-4bit) |",
        "| Training | LoRA, rank 8, scale 20, dropout 0, last 16 of 28 blocks, all linear modules; lr 1e-4; batch 1; 60 steps = 2 epochs; max length 3072; prompt masked; seed 42 |",
        f"| Training examples | 30 VERIFIED ({', '.join(f'{k} {v}' for k, v in manifest['train_categories'].items())}); multiple_authorities unavailable |",
        "| Training context | Demo-only compact context: cited excerpts (quote windows if > 2,400 chars) + one uncited 600-char distractor; mean 3,562 vs 9,307 chars full |",
        "| Evaluation | 50 held-out questions (pilot_v2), zero overlap with training ids and seed documents |",
        "| RAG | Identical stored evidence and prompt per question for every model; app citation parser, mapping and verifier |",
        "| Grader | Blind Claude rubric (correctness, support, hallucination, structure, abstention) + deterministic citation checks |", "",
        "## Files", "",
        "- `summary.md` — main benchmark, before/after, per-question result, statistics, post-hoc diagnostic",
        "- `benchmark_results.json` / `.csv` — every model × question with all metrics and answers",
        "- `per_question_comparison.csv` — LoRA vs Base classification and change flags",
        "- `demo_examples.md` — largest improvements and regressions with answers and evidence",
        "- `benchmark_chart.svg` — measured results chart",
        "- `train_30_manifest.json`, `training_manifest.json` — frozen training selection and overlap checks",
        "- `training_config.json`, `model_metadata.json` — configuration, losses, memory, model and runtime metadata",
        "- `grades.jsonl` — raw graded records; `app_regression_eval.json` — app evaluation suite after the experiment", "",
        "## Reproduce", "",
        "```bash",
        ".venv/bin/python distill/generate_teacher.py --run pilot_lora_teacher --workers 8",
        ".venv/bin/python distill/finetune/pilot_lora_build.py",
        "distill/finetune/.venv/bin/python -m mlx_lm lora -c distill/finetune/pilot_lora_config.yaml",
        "distill/finetune/.venv/bin/python distill/finetune/generate_eval.py --label base --prompts distill/finetune/data/eval_prompts_pilot_v2.jsonl",
        "distill/finetune/.venv/bin/python distill/finetune/generate_eval.py --label lora --adapter artifacts/lora_demo_qwen3_1.7b --prompts distill/finetune/data/eval_prompts_pilot_v2.jsonl",
        ".venv/bin/python distill/finetune/generate_eval_ollama.py --prompts distill/finetune/data/eval_prompts_pilot_v2.jsonl",
        "python3 distill/finetune/repair_lora_outputs.py   # post-hoc diagnostic only",
        ".venv/bin/python distill/finetune/pilot_lora_grade.py --models base lora ollama_base claude lora_repaired",
        ".venv/bin/python distill/finetune/pilot_lora_report.py",
        "```", "",
        "## Caveats", "",
        "- Pilot scale (30 train / 50 eval): results are early signals only.",
        "- Training used a compact context; evaluation uses the full RAG context (distribution shift, by design for time).",
        "- The pre-registered adapter is the final step-60 weights; validation loss rose from step 30 to step 60 (see training_config.json).",
        "- Claude is graded against a Claude-written reference — a ceiling, not an independent score.",
        "- Latencies were measured while other jobs shared the machine; compare them with care.",
        "- Git: base commit 1317809; the distillation code is uncommitted in the working tree.",
    ]
    (OUT / "README.md").write_text("\n".join(readme) + "\n")
    print(json.dumps({"aggregates": aggs, "lora_vs_base": stats}, indent=2))


if __name__ == "__main__":
    main()
