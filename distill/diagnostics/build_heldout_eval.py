"""
Held-out retrieval evaluation set (heldout_v2) — the final generalisation check before scaling.

Built AFTER the retrieval implementation was frozen, from sources never used by the original pilot,
fresh_v1 or each other. Two parts, retrieval-only (no answers):
  * generated — questions from the validated question generator (distill/build_questions.py, run
    `heldout_v2_gen`), converted to evaluation authorities (exact sections; judgments exactly or by
    principle equivalence);
  * templated — exact section references, numbered old/new questions and named-case questions built
    deterministically from corpus metadata with a new sampling seed.

Usage (from the repository root, after `build_questions.py --run heldout_v2_gen ...`):
    .venv/bin/python distill/diagnostics/build_heldout_eval.py
"""
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "distill" / "diagnostics"))
sys.path.insert(0, str(ROOT / "distill"))

from build_fresh_eval import GOOD_RELATIONS, HIGH_VALUE_ACTS, load_corpus, strip, substantive, templated  # noqa: E402
from common import read_jsonl  # noqa: E402
from ingest_statutes import make_statute_doc_id  # noqa: E402

OUT = ROOT / "data" / "distill" / "retrieval_eval" / "heldout_v2"
GENERATED = ROOT / "data" / "distill" / "heldout_v2_gen" / "questions.jsonl"
PILOT_V2 = ROOT / "data" / "distill" / "pilot_v2" / "questions.jsonl"
USED = [
    ROOT / "data" / "distill" / "pilot" / "questions.jsonl",
    ROOT / "data" / "distill" / "retrieval_eval" / "fresh_v1" / "questions.jsonl",
    PILOT_V2,
    GENERATED,
]
SAMPLE_SEED = "heldout-retrieval-eval-v2"


def used_documents():
    used = set()
    for path in USED:
        for item in read_jsonl(path):
            used.update((item.get("seed") or {}).get("doc_ids") or [])
            for authority in item.get("authorities") or (item.get("seed") or {}).get("authorities") or []:
                if authority.get("equivalence", "exact") == "exact":
                    used.update(authority.get("doc_ids") or [])
    return used


def convert_generated():
    """Generated held-out questions, minus any sharing a seed document with the new pilot (generated in parallel)."""
    pilot_docs = {d for q in read_jsonl(PILOT_V2) for d in q["seed"]["doc_ids"]}
    items = []
    for q in read_jsonl(GENERATED):
        if set(q["seed"]["doc_ids"]) & pilot_docs:
            continue
        authorities = []
        for a in q["seed"]["authorities"]:
            label = a["doc_ids"][0] if a["equivalence"] == "exact" else f"principle:{a['source_doc_id']}"
            authorities.append({"label": label, "doc_ids": a["doc_ids"], "kind": a["kind"], "equivalence": a["equivalence"],
                                "intended_chunk_ids": a["intended_chunk_ids"], "evidence_quotes": a.get("evidence_quotes"),
                                "principle_phrase": a.get("principle_phrase")})
        items.append({"id": f"ho-{q['id'][2:]}", "category": q["category"], "question": q["question"], "construction": "generated",
                      "case_law_type": q.get("case_law_type"), "authorities": authorities})
    return items


def main():
    docs, cases = load_corpus()
    excluded = used_documents()
    rng = random.Random(SAMPLE_SEED)
    high_value = [d for d in docs.values() if d["act_id"] in HIGH_VALUE_ACTS and substantive(d) and d["doc_id"] not in excluded]
    mapped = []
    for doc in sorted(docs.values(), key=lambda d: d["doc_id"]):
        if doc["act_id"] not in {"ipc", "crpc", "iea"} or not substantive(doc) or doc["doc_id"] in excluded:
            continue
        for link in doc["corresponds_to"]:
            if isinstance(link, dict) and link.get("relation") in GOOD_RELATIONS:
                target = docs.get(make_statute_doc_id(link.get("act", ""), link.get("section", "")))
                if target and substantive(target) and target["doc_id"] not in excluded:
                    mapped.append((doc, target, link["relation"]))
                break
    well_formed = [c for c in sorted(cases.values(), key=lambda c: c["doc_id"])
                   if len(c["full_text"]) > 6000 and "..." not in (c["title"] or "") and " vs " in f" {c['title'].lower()} "
                   and c["doc_id"] not in excluded]
    selection = {
        "exact_section_reference": [strip(d, 300) for d in rng.sample(high_value, 10)],
        # Only the numbered templates (indices 0 and 1 of every three) are kept below.
        "old_new_law": [{"old": strip(o, 300), "new": strip(n, 300), "relation": r} for o, n, r in rng.sample(mapped, 12)],
        "multiple_sections_seed": [],
        "case_named": [{"doc_id": c["doc_id"], "title": c["title"]} for c in rng.sample(well_formed, min(5, len(well_formed)))],
    }
    templated_items = []
    old_new_index = 0
    for category, question, authorities in templated(selection, docs, cases):
        if category == "old_new_law":
            keep = old_new_index % 3 != 2
            old_new_index += 1
            if not keep:
                continue
        digest = hashlib.sha256(f"{category}|{question}".encode("utf-8")).hexdigest()[:10]
        templated_items.append({"id": f"ho-{digest}", "category": category, "question": question, "construction": "templated",
                                "authorities": authorities})

    items = convert_generated() + templated_items
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "questions.jsonl").open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    summary = {
        "questions": len(items), "by_construction": dict(Counter(i["construction"] for i in items)),
        "by_category": dict(sorted(Counter(i["category"] for i in items).items())),
        "authorities": sum(len(i["authorities"]) for i in items),
        "multi_authority_questions": sum(1 for i in items if len(i["authorities"]) > 1),
        "excluded_source_documents": len(excluded),
    }
    (OUT / "build_report.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
