"""
Retrieval-only regression test. No LLM is called; no answers are generated.

For each question it runs production hybrid_search_with_plan() twice:
  * baseline — the original behaviour, replayed through the same code with RERANK_STRATEGY=weighted and
    MAX_CHUNKS_PER_DOCUMENT=2 (no planning, no reference lookup);
  * fixed    — the current defaults.
and scores both against the intended sources. With --previous it also compares the fixed run with an
earlier results file (e.g. the first RRF implementation), so a later change cannot hide a regression.

An intended "authority" is found when any of its accepted doc_ids is in the final top 5. Pilot seeds
are exact authorities (the diagnostic baseline). Principle authorities accept any judgment containing the
principle's verbatim phrase.

Usage (from the repository root):
    .venv/bin/python distill/diagnostics/retrieval_regression.py run --set pilot --out-dir data/distill/final_validation/retrieval \
        --previous data/distill/pilot/retrieval_fix/pilot_results.json
    .venv/bin/python distill/diagnostics/retrieval_regression.py run --set heldout --out-dir data/distill/final_validation/retrieval
"""
import argparse
import hashlib
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "distill"))

from common import latest_by_id, read_jsonl  # noqa: E402  (also puts src/ on sys.path)
from config import settings  # noqa: E402
from search import hybrid_search_with_plan  # noqa: E402
import vector_store  # noqa: E402

PILOT = ROOT / "data" / "distill" / "pilot"
SETS = {
    "fresh": ROOT / "data" / "distill" / "retrieval_eval" / "fresh_v1" / "questions.jsonl",
    "heldout": ROOT / "data" / "distill" / "retrieval_eval" / "heldout_v2" / "questions.jsonl",
}
TOP_K = 5
BASELINE_SETTINGS = {"rerank_strategy": "weighted", "max_chunks_per_document": 2}
RETRIEVERS = ("semantic", "keyword", "reference", "mapping", "subquery_semantic", "act_scope", "case_law")


@contextmanager
def overridden(**values):
    previous = {key: getattr(settings, key) for key in values}
    for key, value in values.items():
        object.__setattr__(settings, key, value)
    try:
        yield
    finally:
        for key, value in previous.items():
            object.__setattr__(settings, key, value)


def with_retries(call, attempts=4):
    """Network blips (DNS, connection resets) on the embeddings API must not abort a whole run."""
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as error:
            if attempt == attempts:
                raise
            print(f"    retry {attempt}/{attempts - 1} after error: {error}", flush=True)
            time.sleep(10 * attempt)


def load_set(name):
    if name == "pilot":
        records = latest_by_id(read_jsonl(PILOT / "teacher_records.jsonl"))
        items = []
        for q in read_jsonl(PILOT / "questions.jsonl"):
            items.append({
                "id": q["id"], "category": q["category"], "question": q["question"],
                "authorities": [
                    {"label": d, "doc_ids": [d], "kind": "case_law" if d.startswith("NI138") else "statute",
                     "equivalence": "exact", "intended_chunk_ids": None}
                    for d in q["seed"]["doc_ids"]
                ],
                "recorded_pilot_top5": [d["doc_id"] for d in records[q["id"]]["retrieved_context"]],
            })
        return items
    return read_jsonl(SETS[name])


def slim(hit, rank):
    text = hit.get("text") or ""
    return {
        "rank": rank, "doc_id": hit["doc_id"], "chunk_id": hit.get("chunk_id"), "chunk_ids": hit.get("chunk_ids"),
        "chunk_label": hit.get("section"), "context_span": hit.get("context_span"), "source_type": hit.get("source_type"),
        "source": hit.get("source"), "required_reason": hit.get("required_reason"), "semantic_score": hit.get("score"),
        "rerank_score": hit.get("rerank_score"), "retrieval_ranks": hit.get("retrieval_ranks"),
        "text_chars": len(text), "text_sha1": hashlib.sha1(text.encode("utf-8")).hexdigest(), "text_preview": text[:240],
    }


def score(item, hits):
    ids = [h["doc_id"] for h in hits]
    results = []
    for authority in item["authorities"]:
        accepted = set(authority["doc_ids"])
        matched = [h for h in hits if h["doc_id"] in accepted]
        chunk_hit = None
        if authority.get("intended_chunk_ids"):
            wanted = set(authority["intended_chunk_ids"])
            chunk_hit = any(set(h.get("chunk_ids") or [h.get("chunk_id")]) & wanted for h in matched)
        results.append({
            "label": authority["label"], "kind": authority["kind"], "equivalence": authority["equivalence"],
            "accepted_doc_count": len(accepted), "found": bool(matched),
            "matched_doc_ids": [h["doc_id"] for h in matched],
            "rank": ids.index(matched[0]["doc_id"]) + 1 if matched else None,
            "chunk_hit": chunk_hit,
            "via": sorted(set((matched[0].get("retrieval_ranks") or {}).keys()) | set(matched[0].get("found_by_views") or [])) if matched else [],
        })
    return results


def explain_misses(item, authorities, trace):
    fused = {e["doc_id"]: (i + 1, e) for i, e in enumerate(trace.get("fused_top") or [])}
    explained = {}
    for authority, result in zip(item["authorities"], authorities):
        if result["found"]:
            continue
        positions = sorted((fused[d] for d in authority["doc_ids"] if d in fused), key=lambda p: p[0])
        explained[authority["label"]] = (
            {"fused_rank": positions[0][0], "doc_id": positions[0][1]["doc_id"], "rrf_score": positions[0][1]["rrf_score"],
             "retrieval_ranks": positions[0][1]["retrieval_ranks"]}
            if positions else {"fused_rank": None, "note": "not in the top 30 of the fused ranking"}
        )
    return explained


def run(set_name, out_dir, previous_path):
    items = load_set(set_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    previous = {}
    if previous_path:
        previous = {row["id"]: row for row in json.loads(Path(previous_path).read_text())["questions"]}
    with_retries(lambda: hybrid_search_with_plan("warm-up query for Section 138 of the Negotiable Instruments Act", top_k=TOP_K))

    rows = []
    for index, item in enumerate(items, 1):
        vector_store._query_embedding.cache_clear()
        started = time.perf_counter()
        fixed_hits, trace = with_retries(lambda: hybrid_search_with_plan(item["question"], top_k=TOP_K))
        fixed_latency = time.perf_counter() - started
        with overridden(**BASELINE_SETTINGS):
            started = time.perf_counter()
            baseline_hits, _ = with_retries(lambda: hybrid_search_with_plan(item["question"], top_k=TOP_K))
            baseline_latency = time.perf_counter() - started
        baseline = score(item, baseline_hits)
        fixed = score(item, fixed_hits)
        lost = [b["label"] for b, f in zip(baseline, fixed) if b["found"] and not f["found"]]
        gained = [f["label"] for b, f in zip(baseline, fixed) if f["found"] and not b["found"]]
        status = "worse" if lost else "improved" if gained else "unchanged"
        row = {
            "id": item["id"], "category": item["category"], "question": item["question"], "status": status,
            "lost": lost, "gained": gained,
            "baseline": {"authorities": baseline, "top5": [slim(h, r) for r, h in enumerate(baseline_hits, 1)],
                         "latency_s": round(baseline_latency, 3), "distinct_docs": len({h["doc_id"] for h in baseline_hits})},
            "fixed": {"authorities": fixed, "top5": [slim(h, r) for r, h in enumerate(fixed_hits, 1)],
                      "latency_s": round(fixed_latency, 3), "distinct_docs": len({h["doc_id"] for h in fixed_hits}),
                      "retrieval_trace": {k: v for k, v in trace.items() if k != "fused_top"},
                      "misses": explain_misses(item, fixed, trace)},
        }
        if item["id"] in previous:
            earlier = {a["label"]: a["found"] for a in previous[item["id"]]["fixed"]["authorities"]}
            row["vs_previous"] = {
                "lost": [f["label"] for f in fixed if earlier.get(f["label"]) and not f["found"]],
                "gained": [f["label"] for f in fixed if f["found"] and earlier.get(f["label"]) is False],
            }
        if "recorded_pilot_top5" in item:
            row["baseline"]["matches_recorded_pilot_top5"] = [h["doc_id"] for h in baseline_hits] == item["recorded_pilot_top5"]
        rows.append(row)
        print(f"[{index}/{len(items)}] {status:9} {item['id']} {item['category']:24} "
              f"baseline={sum(a['found'] for a in baseline)}/{len(baseline)} fixed={sum(a['found'] for a in fixed)}/{len(fixed)} "
              f"lost={lost} gained={gained} vs_previous={row.get('vs_previous')} {fixed_latency:.2f}s", flush=True)

    result = {
        "set": set_name, "top_k": TOP_K, "baseline_settings": BASELINE_SETTINGS,
        "fixed_settings": {key: getattr(settings, key) for key in (
            "rerank_strategy", "rrf_k", "retrieval_candidate_k", "semantic_score_threshold", "reference_lookup_enabled",
            "mapping_lookup_enabled", "mapping_max_per_reference", "min_discovery_slots", "act_scope_enabled",
            "case_law_subquery_enabled", "section_context_max_chars", "section_context_chunks")},
        "previous_results": str(previous_path) if previous_path else None,
        "metrics": {"baseline": aggregate(rows, "baseline"), "fixed": aggregate(rows, "fixed")},
        "comparison": compare(rows),
        "questions": rows,
    }
    (out_dir / f"{set_name}_results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({"metrics": result["metrics"], "comparison": result["comparison"]}, indent=2))


def aggregate(rows, side):
    authorities = [a for r in rows for a in r[side]["authorities"]]
    found = [a for a in authorities if a["found"]]
    via = Counter(v for a in found for v in a["via"])
    only = Counter(a["via"][0] for a in found if len(a["via"]) == 1)
    chunk_scored = [a for a in found if a["chunk_hit"] is not None]
    latencies = [r[side]["latency_s"] for r in rows]
    per_category = defaultdict(lambda: {"questions": 0, "authorities": 0, "found": 0, "any": 0, "all": 0})
    for r in rows:
        bucket = per_category[r["category"]]
        hits = [a["found"] for a in r[side]["authorities"]]
        bucket["questions"] += 1
        bucket["authorities"] += len(hits)
        bucket["found"] += sum(hits)
        bucket["any"] += any(hits)
        bucket["all"] += all(hits)
    multi = [r for r in rows if len(r[side]["authorities"]) > 1]
    metrics = {
        "intended_sources_retrieved": f"{len(found)}/{len(authorities)}",
        "intended_sources_found": len(found), "intended_sources_total": len(authorities),
        "examples_with_any_intended": sum(1 for r in rows if any(a["found"] for a in r[side]["authorities"])),
        "examples_with_all_intended": sum(1 for r in rows if all(a["found"] for a in r[side]["authorities"])),
        "multi_source_questions_all_found": f"{sum(1 for r in multi if all(a['found'] for a in r[side]['authorities']))}/{len(multi)}",
        "examples": len(rows),
        "recall_pct": round(100 * len(found) / len(authorities), 1) if authorities else None,
        "avg_distinct_docs_in_top5": round(statistics.mean(r[side]["distinct_docs"] for r in rows), 2),
        "latency_s": {"median": round(statistics.median(latencies), 3), "p90": round(sorted(latencies)[int(0.9 * (len(latencies) - 1))], 3),
                      "max": round(max(latencies), 3)},
        "per_category": dict(per_category),
    }
    if side == "fixed":
        metrics["found_sources_contributed_by"] = {name: via.get(name, 0) for name in RETRIEVERS}
        metrics["found_sources_only_by"] = {name: only.get(name, 0) for name in RETRIEVERS}
        requirements = [s for r in rows for s in r["fixed"]["retrieval_trace"].get("requirements_status", [])]
        by_reason = defaultdict(lambda: [0, 0])
        for s in requirements:
            by_reason[s["reason"]][0] += bool(s["satisfied_by"])
            by_reason[s["reason"]][1] += 1
        metrics["detected_requirements_satisfied"] = {reason: f"{hit}/{total}" for reason, (hit, total) in by_reason.items()}
    if chunk_scored:
        metrics["intended_chunk_hit"] = f"{sum(a['chunk_hit'] for a in chunk_scored)}/{len(chunk_scored)} found sources"
    if rows and "matches_recorded_pilot_top5" in rows[0]["baseline"]:
        metrics["baseline_replay_matches_recorded_pilot"] = sum(r["baseline"]["matches_recorded_pilot_top5"] for r in rows)
    return metrics


def compare(rows):
    statuses = Counter(r["status"] for r in rows)
    comparison = {
        "improved": statuses.get("improved", 0), "worse": statuses.get("worse", 0), "unchanged": statuses.get("unchanged", 0),
        "improved_ids": [r["id"] for r in rows if r["status"] == "improved"],
        "regressions_vs_baseline": [{"id": r["id"], "category": r["category"], "lost": r["lost"], "gained": r["gained"],
                                     "misses": r["fixed"]["misses"]} for r in rows if r["status"] == "worse"],
    }
    compared = [r for r in rows if "vs_previous" in r]
    if compared:
        comparison["vs_previous"] = {
            "questions_compared": len(compared),
            "sources_lost": sum(len(r["vs_previous"]["lost"]) for r in compared),
            "sources_gained": sum(len(r["vs_previous"]["gained"]) for r in compared),
            "regressions": [{"id": r["id"], "category": r["category"], "lost": r["vs_previous"]["lost"], "misses": r["fixed"]["misses"]}
                            for r in compared if r["vs_previous"]["lost"]],
        }
    return comparison


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    runner = sub.add_parser("run")
    runner.add_argument("--set", choices=["pilot", "fresh", "heldout"], required=True)
    runner.add_argument("--out-dir", default=str(ROOT / "data" / "distill" / "final_validation" / "retrieval"))
    runner.add_argument("--previous", default=None, help="Earlier results file to compare the fixed run against.")
    args = parser.parse_args()
    run(args.set, Path(args.out_dir), args.previous)


if __name__ == "__main__":
    main()
