"""
Assembles data/distill/pilot/retrieval_fix_report.json from the two regression runs and the checker
tests, and prints the tables used in retrieval_fix_report.md. Reads only; recomputes nothing.

Usage (from the repository root, after retrieval_regression.py runs for both sets):
    .venv/bin/python distill/diagnostics/assemble_fix_report.py
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "data" / "distill" / "pilot"
FIX = PILOT / "retrieval_fix"
DIAGNOSTIC_BASELINE = {"intended_sources_found": 45, "intended_sources_total": 62, "examples_with_any_intended": 39, "examples_with_all_intended": 38}
KNOWN_FAILURES = {
    "q-3185dbed0d6d": "definition: Special Court (Securities) Act s2 dropped by rerank",
    "q-520bf8984839": "definition: NaBFID s2 sub-chunk",
    "q-db2f8b89a1b6": "punishment: Legal Metrology s32 dropped by rerank",
    "q-835e1e9f9fe5": "multiple_sections: IEA s10 + s11 named",
    "q-6006b8fb9ef6": "multiple_sections: CrPC s180 + s181 (fact pattern)",
    "q-0e66cd570330": "fact_pattern: BNS s218 dropped by rerank",
    "q-c4dcb3eb2ee9": "old_new_law: IPC s362 -> BNS s138",
    "q-89d14510bd1b": "case_law: principle-level (grading issue)",
    "q-ae393c6b3d7b": "case_law: principle-level (grading issue)",
    "q-cee5a99865bb": "multiple_authorities: NI s141 + victim-appeal judgment",
    "q-c69f7823801d": "multiple_authorities: NI s140 + judgment",
    "q-5c502c87752e": "multiple_sections (verified): Companies Act s46 missed",
}


def main():
    pilot = json.loads((FIX / "pilot_results.json").read_text())
    fresh = json.loads((FIX / "fresh_results.json").read_text())
    checker = json.loads((FIX / "checker_fix_tests.json").read_text())

    def found_map(row, side):
        return {a["label"]: a for a in row[side]["authorities"]}

    known = []
    for row in pilot["questions"]:
        if row["id"] not in KNOWN_FAILURES:
            continue
        base, fixed = found_map(row, "baseline"), found_map(row, "fixed")
        known.append({
            "id": row["id"], "failure": KNOWN_FAILURES[row["id"]], "status": row["status"],
            "authorities": [{"label": label, "baseline_found": base[label]["found"], "fixed_found": fixed[label]["found"],
                             "fixed_rank": fixed[label]["rank"], "via": fixed[label]["via"],
                             "fused_rank": row["fixed"]["diagnostics"]["intended"][label].get("fused_rank"),
                             "retrieval_ranks": row["fixed"]["diagnostics"]["intended"][label].get("retrieval_ranks")}
                            for label in base],
            "references": [r["doc_id"] for r in row["fixed"]["diagnostics"]["references"]],
            "mapped": [m["doc_id"] for m in row["fixed"]["diagnostics"]["mapped"]],
        })

    def misses(result):
        rows = []
        for row in result["questions"]:
            for a in row["fixed"]["authorities"]:
                if not a["found"]:
                    rows.append({"id": row["id"], "category": row["category"], "label": a["label"],
                                 "diagnostic": row["fixed"]["diagnostics"]["intended"][a["label"]],
                                 "references": [r["doc_id"] for r in row["fixed"]["diagnostics"]["references"]],
                                 "mapped": [m["doc_id"] for m in row["fixed"]["diagnostics"]["mapped"]]})
        return rows

    report = {
        "stage": "FIX -> RETEST (retrieval only; no LLM calls, no teacher answers)",
        "diagnostic_baseline_recorded": DIAGNOSTIC_BASELINE,
        "pilot_50": {"metrics": pilot["metrics"], "comparison": pilot["comparison"], "known_failures": known,
                     "remaining_misses": misses(pilot), "settings": {"baseline": pilot["baseline_settings"], "fixed": pilot["fixed_settings"]}},
        "fresh_set": {"metrics": fresh["metrics"], "comparison": fresh["comparison"], "remaining_misses": misses(fresh),
                      "questions_file": "data/distill/retrieval_eval/fresh_v1/questions.jsonl"},
        "checker_fix_tests": checker,
        "raw_results": {"pilot": "data/distill/pilot/retrieval_fix/pilot_results.json",
                        "fresh": "data/distill/pilot/retrieval_fix/fresh_results.json"},
        "per_question": {"pilot": pilot["questions"], "fresh": fresh["questions"]},
    }
    (PILOT / "retrieval_fix_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

    for name, result in (("PILOT 50", pilot), ("FRESH", fresh)):
        b, f = result["metrics"]["baseline"], result["metrics"]["fixed"]
        print(f"\n===== {name} =====")
        for key in ("intended_sources_retrieved", "examples_with_any_intended", "examples_with_all_intended", "recall_pct",
                    "avg_distinct_docs_in_top5", "distinct_docs_in_top5", "latency_s", "intended_chunk_hit",
                    "baseline_replay_matches_recorded_pilot"):
            if key in b or key in f:
                print(f"  {key:40} baseline={b.get(key)}  fixed={f.get(key)}")
        print("  contributed_by:", f.get("found_sources_contributed_by"), " only_by:", f.get("found_sources_only_by"))
        print("  comparison:", {k: v for k, v in result["comparison"].items() if k != "regressions"})
        for reg in result["comparison"]["regressions"]:
            print("  REGRESSION:", json.dumps(reg)[:600])
        print("  per category (baseline found/all -> fixed found/all):")
        for cat in f["per_category"]:
            bc, fc = b["per_category"][cat], f["per_category"][cat]
            print(f"    {cat:26} q={fc['questions']:2}  sources {bc['found']}/{bc['authorities']} -> {fc['found']}/{fc['authorities']}"
                  f"   all {bc['all']} -> {fc['all']}")
    print("\n===== KNOWN PILOT FAILURES =====")
    for k in known:
        print(f"  {k['id']} [{k['status']}] {k['failure']}  refs={k['references']} mapped={k['mapped']}")
        for a in k["authorities"]:
            print(f"      {a['label'][:60]:60} base={a['baseline_found']!s:5} fixed={a['fixed_found']!s:5} rank={a['fixed_rank']} via={a['via']} fused_rank={a['fused_rank']} lists={a['retrieval_ranks']}")
    for name, result in (("PILOT", pilot), ("FRESH", fresh)):
        print(f"\n===== REMAINING MISSES ({name}) =====")
        for m in misses(result):
            d = m["diagnostic"]
            print(f"  {m['id']} {m['category']:24} {m['label'][:58]:58} fused_rank={d.get('fused_rank')} lists={d.get('retrieval_ranks')} refs={m['references']} mapped={m['mapped']}")


if __name__ == "__main__":
    main()
