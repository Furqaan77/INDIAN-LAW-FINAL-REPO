"""
Read-only ranking ablation for the 50-example pilot.

Rebuilds the production candidate pool (semantic top-15 chunks above threshold + keyword top-15 documents,
exactly as hybrid_search merges them) and re-orders that same pool with alternative formulas, so ranking
effects can be separated from recall effects. Nothing in src/ is changed; this only measures.

Usage (from the repository root):
    .venv/bin/python distill/diagnostics/rerank_ablation.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "distill"))

from common import latest_by_id, read_jsonl  # noqa: E402  (also puts src/ on sys.path)
from config import settings  # noqa: E402
from db import search_keyword  # noqa: E402
from rerank import rerank  # noqa: E402
from search import _keyword_hit_to_context_hit, semantic_search  # noqa: E402

PILOT = ROOT / "data" / "distill" / "pilot"
OUT = PILOT / "diagnostics"
TOP_K = settings.default_top_k


def production_pool(query, depth):
    semantic = semantic_search(query, top_k=depth)
    keyword = search_keyword(query, limit=depth)
    seen = {h["doc_id"] for h in semantic}
    merged = list(semantic)
    for kw in keyword:
        if kw["doc_id"] not in seen:
            merged.append(_keyword_hit_to_context_hit(kw))
            seen.add(kw["doc_id"])
    return semantic, keyword, merged


def cap(ordered_hits, per_doc):
    counts, out = defaultdict(int), []
    for h in ordered_hits:
        if counts[h["doc_id"]] >= per_doc:
            continue
        counts[h["doc_id"]] += 1
        out.append(h)
        if len(out) >= TOP_K:
            break
    return [h["doc_id"] for h in out]


def rrf(semantic, keyword, merged, per_doc, k=60):
    semantic_doc_rank, keyword_doc_rank = {}, {}
    for hit in semantic:
        semantic_doc_rank.setdefault(hit["doc_id"], len(semantic_doc_rank) + 1)
    for hit in keyword:
        keyword_doc_rank.setdefault(hit["doc_id"], len(keyword_doc_rank) + 1)

    def score(h):
        s = semantic_doc_rank.get(h["doc_id"])
        w = keyword_doc_rank.get(h["doc_id"])
        return (1 / (k + s) if s else 0) + (1 / (k + w) if w else 0) + (h.get("score") or 0) * 1e-6

    return cap(sorted(merged, key=score, reverse=True), per_doc)


def strategies(query):
    semantic, keyword, merged = production_pool(query, settings.retrieval_candidate_k)
    deep_semantic, deep_keyword, deep_merged = production_pool(query, 50)
    return {
        "A_production": [h["doc_id"] for h in rerank(merged, query, top_k=TOP_K)],
        "B_semantic_order_only": cap(sorted(semantic, key=lambda h: h["score"], reverse=True), settings.max_chunks_per_document),
        "C_production_score_1_chunk_per_doc": [h["doc_id"] for h in rerank(merged, query, top_k=TOP_K, max_per_doc=1)],
        "D_rrf_pool15_1_chunk_per_doc": rrf(semantic, keyword, merged, per_doc=1),
        "E_rrf_pool50_1_chunk_per_doc": rrf(deep_semantic, deep_keyword, deep_merged, per_doc=1),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    questions = read_jsonl(PILOT / "questions.jsonl")
    records = latest_by_id(read_jsonl(PILOT / "teacher_records.jsonl"))
    rows = []
    for q in questions:
        intended = q["seed"]["doc_ids"]
        result = strategies(q["question"])
        pilot_ids = [d["doc_id"] for d in records[q["id"]]["retrieved_context"]]
        rows.append({
            "id": q["id"], "category": q["category"], "status": records[q["id"]]["status"], "intended": intended,
            "production_matches_pilot": result["A_production"] == pilot_ids,
            "strategies": {name: {"ids": ids, "distinct_docs": len(set(ids)),
                                  "hits": [d for d in intended if d in ids]} for name, ids in result.items()},
        })
        print(q["id"], {n: len(v["hits"]) for n, v in rows[-1]["strategies"].items()}, flush=True)

    summary = {}
    for name in rows[0]["strategies"]:
        hit_docs = sum(len(r["strategies"][name]["hits"]) for r in rows)
        any_hit = sum(1 for r in rows if r["strategies"][name]["hits"])
        all_hit = sum(1 for r in rows if len(r["strategies"][name]["hits"]) == len(r["intended"]))
        lost = [r["id"] for r in rows if set(r["strategies"]["A_production"]["hits"]) - set(r["strategies"][name]["hits"])]
        gained = [r["id"] for r in rows if set(r["strategies"][name]["hits"]) - set(r["strategies"]["A_production"]["hits"])]
        avg_distinct = sum(r["strategies"][name]["distinct_docs"] for r in rows) / len(rows)
        summary[name] = {"intended_docs_hit": hit_docs, "intended_docs_total": sum(len(r["intended"]) for r in rows),
                         "examples_any_hit": any_hit, "examples_all_hit": all_hit, "avg_distinct_docs": round(avg_distinct, 2),
                         "examples_gained_vs_production": gained, "examples_lost_vs_production": lost}
    output = {"summary": summary, "rows": rows,
              "production_matches_pilot": sum(r["production_matches_pilot"] for r in rows)}
    (OUT / "rerank_ablation.json").write_text(json.dumps(output, indent=2))
    print(json.dumps(summary, indent=2))
    print("production reproduces pilot:", output["production_matches_pilot"], "/ 50")


if __name__ == "__main__":
    main()
