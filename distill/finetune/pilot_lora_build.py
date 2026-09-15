"""
LoRA distillation pilot — training-set selection and compact training representation.

1. Selects 30 VERIFIED teacher examples from data/distill/pilot_lora_teacher (Claude + IndianLawGPT RAG),
   round-robin across categories so every available category is represented, and rejects any example that
   shares a seed document with, or is a near-duplicate (token Jaccard >= 0.5) of, a held-out benchmark question.
2. Builds a DEMO-ONLY compact context per example (the production RAG is untouched):
     - every excerpt the teacher actually cited, in original retrieval order, with the same
       "--- doc_id: ... | title (location) | section: ... ---" header the app uses (rag_chain.build_context);
       an excerpt longer than MAX_CITED_CHARS is cut to windows around the teacher's evidence quotes,
       and an example is dropped if any quote would not remain verbatim;
     - plus ONE uncited excerpt (the highest-ranked one), cut to DISTRACTOR_CHARS, so the student still has to
       choose which evidence supports the answer.
   The system prompt, question and dataset answer instruction are unchanged; the target is the teacher's
   structured output {"citations": [...], "answer": ...}.
3. Writes train/valid JSONL (MLX chat format), the frozen manifest, and the list of held-out benchmark ids.

Run with the app venv:
    .venv/bin/python distill/finetune/pilot_lora_build.py
"""
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "distill"))

from common import jaccard, question_tokens, read_jsonl  # noqa: E402  (also puts src/ on sys.path)
from rag_chain import SYSTEM_PROMPT, build_context  # noqa: E402

SEED = 42
N_TRAIN = 30
MAX_CITED_CHARS = 2400
QUOTE_WINDOW_CHARS = 700
DISTRACTOR_CHARS = 600
TEACHER_RUN = ROOT / "data" / "distill" / "pilot_lora_teacher"
EVAL_PROMPTS = ROOT / "distill" / "finetune" / "data" / "eval_prompts_pilot_v2.jsonl"
OUT = ROOT / "data" / "distill" / "pilot_lora"
TRAIN_DATA = ROOT / "distill" / "finetune" / "data_pilot_lora"


def norm(text):
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def windows_around_quotes(text, quotes):
    """Keeps windows of the excerpt around each quote; returns None if a quote cannot be kept verbatim."""
    spans = []
    for quote in quotes:
        head = quote[:40]
        position = text.find(head)
        if position < 0:
            return None
        spans.append((max(0, position - QUOTE_WINDOW_CHARS // 2), min(len(text), position + len(quote) + QUOTE_WINDOW_CHARS // 2)))
    spans.sort()
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return " […] ".join(text[s:e] for s, e in merged)


def hit(doc, text):
    return {"doc_id": doc["doc_id"], "title": doc.get("title"), "court": doc.get("court"), "date": doc.get("date"),
            "section": doc.get("chunk_label"), "file_name": None, "page_start": None, "page_end": None, "text": text}


def compact(record):
    quotes_by_doc = defaultdict(list)
    for citation in record["target"]["citations"]:
        quotes_by_doc[citation["doc_id"]].append(citation["evidence_quote"])
    hits, kept, trimmed = [], [], []
    distractor = None
    for doc in record["retrieved_context"]:
        text = doc.get("text") or ""
        if doc["doc_id"] in quotes_by_doc:
            if len(text) > MAX_CITED_CHARS:
                cut = windows_around_quotes(text, quotes_by_doc[doc["doc_id"]])
                if cut is None:
                    return None, "evidence_quote_not_locatable_for_trimming"
                text = cut
                trimmed.append(doc["doc_id"])
            hits.append(hit(doc, text))
            kept.append(doc["doc_id"])
        elif distractor is None:
            distractor = doc
            hits.append(hit(doc, text[:DISTRACTOR_CHARS]))
    context = build_context(hits)
    for citation in record["target"]["citations"]:
        if norm(citation["evidence_quote"]) not in norm(context):
            return None, "evidence_quote_lost_in_compact_context"
    instruction = record["teacher_prompt"]["user_content"].split(f"Question: {record['question']}\n\n", 1)[1]
    user = f"Excerpts:\n{context}\n\nQuestion: {record['question']}\n\n{instruction}"
    info = {"cited_doc_ids": kept, "trimmed_doc_ids": trimmed, "distractor_doc_id": distractor["doc_id"] if distractor else None,
            "full_user_chars": len(record["teacher_prompt"]["user_content"]), "compact_user_chars": len(user)}
    return user, info


def main():
    eval_items = read_jsonl(EVAL_PROMPTS)
    eval_docs = {d for item in eval_items for d in item["seed"]["doc_ids"]}
    eval_tokens = [question_tokens(item["question"]) for item in eval_items]
    records = {r["id"]: r for r in read_jsonl(TEACHER_RUN / "teacher_records.jsonl")}

    candidates, rejected = defaultdict(list), []
    for record in sorted(records.values(), key=lambda r: hashlib.sha256(f"{SEED}:{r['id']}".encode()).hexdigest()):
        reason = None
        if record["quality_status"] != "VERIFIED":
            reason = f"not_verified:{record['quality_status']}"
        elif record["checks"]["pipeline_error"] or not record["target"]["citations"] or not record["teacher_answer"]:
            reason = "malformed_or_pipeline_error"
        elif set(record["seed"]["doc_ids"]) & eval_docs:
            reason = "shares_seed_document_with_benchmark"
        elif max((jaccard(question_tokens(record["question"]), t) for t in eval_tokens), default=0) >= 0.5:
            reason = "near_duplicate_of_benchmark_question"
        if reason:
            rejected.append({"id": record["id"], "category": record["category"], "reason": reason})
            continue
        user, info = compact(record)
        if user is None:
            rejected.append({"id": record["id"], "category": record["category"], "reason": info})
            continue
        candidates[record["category"]].append((record, user, info))

    selected, round_index = [], 0
    while len(selected) < N_TRAIN and any(len(v) > round_index for v in candidates.values()):
        for category in sorted(candidates):
            if len(selected) < N_TRAIN and len(candidates[category]) > round_index:
                selected.append(candidates[category][round_index])
        round_index += 1
    chosen_ids = {r["id"] for r, _, _ in selected}
    spare = [c for cat in sorted(candidates) for c in candidates[cat] if c[0]["id"] not in chosen_ids]
    validation = spare[:3]

    def example(record, user):
        target = json.dumps({"citations": record["target"]["citations"], "answer": record["target"]["answer"]}, ensure_ascii=False)
        return {"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user},
                             {"role": "assistant", "content": target}]}

    TRAIN_DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (TRAIN_DATA / "train.jsonl").write_text("".join(json.dumps(example(r, u), ensure_ascii=False) + "\n" for r, u, _ in selected))
    (TRAIN_DATA / "valid.jsonl").write_text("".join(json.dumps(example(r, u), ensure_ascii=False) + "\n" for r, u, _ in validation))

    manifest = {
        "experiment": "IndianLawGPT — Qwen3-1.7B LoRA Distillation Pilot",
        "teacher": "Claude (claude-sonnet-5) + IndianLawGPT RAG", "teacher_run": str(TEACHER_RUN.relative_to(ROOT)),
        "selection_rule": "VERIFIED only; no pipeline errors or malformed targets; no seed-document overlap and no near-duplicate "
                          "(token Jaccard >= 0.5) with any of the 50 benchmark questions; order fixed by sha256(seed:id); "
                          "round-robin across categories until 30.",
        "compact_context_rule": {"cited_excerpts": "all cited excerpts in retrieval order; cut to windows of "
                                                   f"{QUOTE_WINDOW_CHARS} chars around evidence quotes if longer than {MAX_CITED_CHARS} chars",
                                 "distractor": f"highest-ranked uncited excerpt, first {DISTRACTOR_CHARS} chars",
                                 "unchanged": "system prompt, question, dataset answer instruction, excerpt headers, teacher target"},
        "seed": SEED,
        "train": [{"id": r["id"], "category": r["category"], "answer_type": r["answer_type"], "question": r["question"],
                   "why_selected": f"category slot {r['category']} (round-robin)", "source_ids": r["source_ids"], **i}
                  for r, _, i in selected],
        "validation": [{"id": r["id"], "category": r["category"]} for r, _, _ in validation],
        "train_categories": dict(Counter(r["category"] for r, _, _ in selected)),
        "categories_unavailable": sorted({"multiple_authorities"} - set(candidates)),
        "rejected_candidates": rejected,
        "verified_available": sum(len(v) for v in candidates.values()),
        "benchmark": {"file": str(EVAL_PROMPTS.relative_to(ROOT)), "questions": len(eval_items),
                      "ids": [i["id"] for i in eval_items]},
        "overlap_checks": {"train_ids_in_benchmark": len(chosen_ids & {i["id"] for i in eval_items}),
                           "train_seed_docs_in_benchmark_seeds": sum(1 for r, _, _ in selected if set(r["seed"]["doc_ids"]) & eval_docs)},
        "mean_compact_user_chars": round(sum(i["compact_user_chars"] for _, _, i in selected) / max(1, len(selected))),
        "mean_full_user_chars": round(sum(i["full_user_chars"] for _, _, i in selected) / max(1, len(selected))),
    }
    (OUT / "train_30_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    (OUT / "training_manifest.json").write_text(json.dumps({k: manifest[k] for k in ("experiment", "teacher", "selection_rule", "compact_context_rule", "seed", "train_categories", "categories_unavailable", "overlap_checks", "mean_compact_user_chars", "mean_full_user_chars")} | {"train_ids": sorted(chosen_ids), "validation_ids": [r["id"] for r, _, _ in validation]}, indent=2, ensure_ascii=False))
    print(json.dumps({k: manifest[k] for k in ("verified_available", "train_categories", "categories_unavailable", "overlap_checks", "mean_compact_user_chars", "mean_full_user_chars")}, indent=2))
    print("selected:", len(selected), "validation:", len(validation), "rejected:", Counter(r["reason"].split(":")[0] for r in rejected))


if __name__ == "__main__":
    main()
