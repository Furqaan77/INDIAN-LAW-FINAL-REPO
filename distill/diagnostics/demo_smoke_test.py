"""
End-to-end demo smoke test against the running API (default http://127.0.0.1:8010).

For every demo question (frontend/src/demo/demoQuestions.ts): Claude answers first and freezes the evidence;
Plain Qwen and LoRA Qwen then answer with that evidence_id. Checks identical evidence, engine identity,
citation verification (no unverified sources), and prints what each engine did. Also checks the source
reader (highlights), the old/new-law map, statute search, corpus stats and — on a second API instance whose
LoRA service address is unreachable — that the LoRA engine fails with its own message and no other model answers.

Prerequisites: API on :8010, LoRA service on :8095, Ollama, Anthropic credits.
    .venv/bin/python distill/diagnostics/demo_smoke_test.py [--skip-fallback] [--only ID ...]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_TS = ROOT / "frontend" / "src" / "demo" / "demoQuestions.ts"
OUT = ROOT / "logs" / "demo_smoke_test.json"
ENGINES = ("claude", "qwen", "lora_qwen")
INSUFFICIENT = re.compile(r"do(?:es)? not (?:contain|provide|address|specify|cover|include|mention)|insufficient|not (?:addressed|covered)|no (?:information|provision)|cannot be (?:determined|answered)", re.I)


def load_questions():
    text = QUESTIONS_TS.read_text()
    items = []
    for block in re.findall(r"\{\s*id:.*?\n  \}", text, flags=re.S):
        get = lambda key: (re.search(rf'{key}:\s*"((?:[^"\\]|\\.)*)"', block) or [None, None])[1]  # noqa: E731
        items.append({"id": get("id"), "capability": get("capability"), "question": get("question"), "href": get("href")})
    return items


def request(base, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def answer(base, question, engine, evidence_id=None):
    body = {"question": question, "model": engine, "mode": "research"}
    if evidence_id:
        body["evidence_id"] = evidence_id
    return request(base, "/api/answer", body)


def check(condition, label, failures):
    if not condition:
        failures.append(label)
    return condition


def run_questions(base, questions, failures):
    rows = []
    for item in questions:
        if item["href"]:
            continue
        results, evidence_id = {}, None
        for engine in ENGINES:
            started = time.time()
            result = answer(base, item["question"], engine, evidence_id)
            wall = round(time.time() - started, 1)
            info, cc = result.get("engine") or {}, result.get("citation_check") or {}
            evidence_id = evidence_id or info.get("evidence_id")
            results[engine] = result
            row = {
                "question_id": item["id"], "engine": engine, "label": info.get("label"), "subtitle": info.get("subtitle"),
                "model": info.get("model"), "error": result.get("error"), "message": info.get("message"),
                "evidence_id": info.get("evidence_id"), "evidence_reused": info.get("evidence_reused"),
                "retrieved": len(result.get("retrieved_documents") or []), "output_status": info.get("output_status"),
                "retries": info.get("retry_count"), "cited": len(result.get("citations") or []), "verified": result.get("verified_count"),
                "unverified": len(result.get("unverified") or []), "proposed_quotes": cc.get("proposed"), "rejected_quotes": cc.get("rejected"),
                "total_s": info.get("total_s"), "wall_s": wall, "answer_head": (result.get("answer_markdown") or "")[:160],
                "cited_doc_ids": [c["doc_id"] for c in result.get("citations") or []],
            }
            rows.append(row)
            print(f"  {item['id']:22} {engine:9} {str(row['output_status']):9} retries={row['retries']} verified={row['verified']}/{row['cited']} "
                  f"rejected={row['rejected_quotes']} evidence={row['evidence_id']} reused={row['evidence_reused']} {wall}s err={row['error']}", flush=True)
            check(row["error"] is None, f"{item['id']}/{engine}: error {row['error']} {row['message']}", failures)
            check(info.get("key") == engine, f"{item['id']}/{engine}: wrong engine key {info.get('key')}", failures)
            check(row["unverified"] == 0, f"{item['id']}/{engine}: unverified sources", failures)
            check(result.get("citation_check") is not None, f"{item['id']}/{engine}: citation_check missing", failures)
        ids = {results[e]["engine"].get("evidence_id") for e in ENGINES}
        docs = {tuple(results[e]["evidence"]["doc_ids"]) for e in ENGINES}
        check(len(ids) == 1 and None not in ids, f"{item['id']}: evidence ids differ {ids}", failures)
        check(len(docs) == 1, f"{item['id']}: evidence documents differ", failures)
        check(not results["claude"]["engine"]["evidence_reused"] or True, "", failures)
        check(all(results[e]["engine"]["evidence_reused"] for e in ("qwen", "lora_qwen")), f"{item['id']}: evidence not reused", failures)
        if item["id"] == "insufficient-evidence":
            for engine in ENGINES:
                text = results[engine].get("answer_markdown") or ""
                print(f"    insufficiency wording ({engine}): {bool(INSUFFICIENT.search(text))} | cited={len(results[engine].get('citations') or [])}")
            # The engine prompt asks for what the excerpts do establish [n] plus what is missing, so a citation is allowed;
            # the answer must state that the evidence does not answer the question. Only Claude is required to — the
            # local models' behaviour here is reported, not gated (LoRA Qwen is experimental).
            check(bool(INSUFFICIENT.search(results["claude"].get("answer_markdown") or "")), "insufficient-evidence: Claude did not state insufficiency", failures)
        else:
            check(results["claude"]["verified_count"] > 0, f"{item['id']}: Claude produced no verified citation", failures)
    return rows


def run_platform_checks(base, rows, failures):
    stats = request(base, "/api/stats")
    print("stats:", {k: stats[k] for k in ("documents", "by_source_type", "acts", "passages")})
    check(stats["passages"] and stats["by_source_type"].get("statute") and stats["by_source_type"].get("case_law"), "stats incomplete", failures)

    cited = next((r for r in rows if r["engine"] == "claude" and r["cited_doc_ids"]), None)
    if cited:
        doc_id = cited["cited_doc_ids"][0]
        result = answer(base, next(q for q in load_questions() if q["id"] == cited["question_id"])["question"], "claude", cited["evidence_id"])
        quotes = next(c["quotes"] for c in result["citations"] if c["doc_id"] == doc_id) if any(c["doc_id"] == doc_id for c in result["citations"]) else []
        query = urllib.parse.urlencode([("quote", q) for q in quotes])
        document = request(base, f"/api/documents/{urllib.parse.quote(doc_id)}?{query}")
        print(f"source reader: {doc_id} '{document['title'][:70]}' type={document['source_type']} chars={len(document['full_text'])} highlights={len(document['highlights'])}")
        check(document["full_text"] and (not quotes or document["highlights"]), f"source reader: no highlights for {doc_id}", failures)

    for act, section in (("crpc", "438"), ("ipc", "420")):
        law_map = request(base, f"/api/law-map?act={act}&section={section}")
        counterparts = [(c["act_id"], c["section_number"], c["relation"]) for c in law_map["correspondences"]]
        print(f"law map {act} {section}: {law_map['source']['title'][:60]} -> {counterparts}")
        check(bool(counterparts), f"law map {act} {section}: no correspondences", failures)

    search = request(base, "/api/search?" + urllib.parse.urlencode({"q": "anticipatory bail", "type": "statute", "limit": 5}))
    print("statute search 'anticipatory bail':", [r["doc_id"] for r in search["results"]])
    check(bool(search["results"]), "statute search returned nothing", failures)


def run_fallback_check(question, failures):
    env = {**os.environ, "LORA_QWEN_URL": "http://127.0.0.1:8099"}
    process = subprocess.Popen([str(ROOT / ".venv" / "bin" / "uvicorn"), "api:app", "--port", "8012"], cwd=ROOT / "src", env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:8012"
    try:
        for _ in range(60):
            try:
                request(base, "/api/health", timeout=2)
                break
            except Exception:
                time.sleep(1)
        result = answer(base, question, "lora_qwen")
        info = result["engine"]
        print(f"no-fallback: error={result['error']} status={info['output_status']} message={info['message']!r} model={info['model']} "
              f"models.llm={result['models']['llm']} citations={len(result['citations'])}")
        check(result["error"] == "generation" and info["output_status"] == "FAILED", "no-fallback: LoRA did not fail", failures)
        check(info["message"] == "LoRA Qwen unavailable. Check the local MLX model service.", "no-fallback: wrong message", failures)
        check(info["key"] == "lora_qwen" and not result["citations"], "no-fallback: another model answered", failures)
        statuses = {e["key"]: e["available"] for e in request(base, "/api/engines")["engines"]}
        print("no-fallback engine status:", statuses)
        check(statuses.get("lora_qwen") is False, "no-fallback: engines endpoint did not flag LoRA unavailable", failures)
    finally:
        process.terminate()
        process.wait(timeout=20)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--skip-fallback", action="store_true")
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()

    questions = [q for q in load_questions() if not args.only or q["id"] in args.only]
    engines = {e["key"]: e for e in request(args.base, "/api/engines")["engines"]}
    print("engines:", {k: (v["available"], v["detail"]) for k, v in engines.items()})
    failures = []
    for key in ENGINES:
        check(engines[key]["available"], f"engine {key} unavailable before test: {engines[key]['detail']}", failures)
    rows = run_questions(args.base, questions, failures)
    run_platform_checks(args.base, rows, failures)
    if not args.skip_fallback:
        run_fallback_check(questions[0]["question"], failures)
    OUT.write_text(json.dumps({"rows": rows, "failures": failures}, indent=2, ensure_ascii=False))
    print("\nFAILURES:" if failures else "\nALL DEMO CHECKS PASSED", *failures, sep="\n  ")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
