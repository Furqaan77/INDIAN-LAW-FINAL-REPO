"""
Read-only retrieval diagnostics for the 50-example distillation pilot.

Calls the production retrieval functions (semantic_search, search_keyword, hybrid_search and the
vector store's filtered query) with the pilot questions and with controlled query variants. It changes
nothing in src/, makes no LLM calls, and writes only to data/distill/pilot/diagnostics/.

Variants built from the intended source's own metadata are marked oracle=True: they show what WOULD
retrieve the source if that information were available, not what the current system can do unaided.

Usage (from the repository root):
    .venv/bin/python distill/diagnostics/retrieval_probe.py
"""
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "distill"))

from common import SEED, latest_by_id, question_tokens, read_jsonl  # noqa: E402  (also puts src/ on sys.path)
from config import settings  # noqa: E402
from db import get_connection, search_keyword  # noqa: E402
from ingest_statutes import make_statute_doc_id  # noqa: E402
from rag_chain import normalize_text  # noqa: E402
from search import hybrid_search, semantic_search  # noqa: E402
from vector_store import get_vector_store  # noqa: E402

PILOT = ROOT / "data" / "distill" / "pilot"
OUT = PILOT / "diagnostics"
SEMANTIC_DEPTH = 100
KEYWORD_DEPTH = 200
ABBREVIATIONS = [
    (r"\bipc\b", "ipc"), (r"\bcr\.?\s?p\.?\s?c\b", "crpc"), (r"\bbnss\b", "bnss"), (r"\bbns\b", "bns"),
    (r"\bbsa\b", "bsa"), (r"\biea\b", "iea"), (r"\bn\.?\s?i\.?\s?act\b", "ni-act"),
]
SECTION_REF = re.compile(r"\b(?:section|sec\.?|s\.)\s*(\d+[A-Z]?)", re.IGNORECASE)


def norm(text):
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def load_metadata():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT doc_id, title, source_type, full_text, metadata_json FROM documents").fetchall()
    finally:
        conn.close()
    meta, acts = {}, {}
    for row in rows:
        m = json.loads(row["metadata_json"] or "{}")
        meta[row["doc_id"]] = {
            "title": row["title"], "source_type": row["source_type"], "act_id": m.get("act_id"),
            "act_title": m.get("act_title"), "section": m.get("section_number"), "heading": m.get("section_heading"),
            "corresponds_to": m.get("corresponds_to") or [], "text": row["full_text"],
        }
        if m.get("act_id"):
            acts.setdefault(m["act_id"], {"title": m.get("act_title"), "doc_ids": []})["doc_ids"].append(row["doc_id"])
    return meta, acts


def stage_ranks(query, intended):
    """Where each intended document sits at every stage of the production retrieval path."""
    semantic = semantic_search(query, top_k=SEMANTIC_DEPTH, threshold=0.0)
    semantic_rank = {}
    for rank, hit in enumerate(semantic, 1):
        semantic_rank.setdefault(hit["doc_id"], {"rank": rank, "score": round(hit["score"], 4)})
    keyword_rank = {}
    for rank, hit in enumerate(search_keyword(query, limit=KEYWORD_DEPTH), 1):
        keyword_rank.setdefault(hit["doc_id"], rank)
    final = hybrid_search(query, top_k=settings.default_top_k)
    final_ids = [h["doc_id"] for h in final]

    per_doc = {}
    for doc_id in intended:
        s, k = semantic_rank.get(doc_id), keyword_rank.get(doc_id)
        in_semantic_pool = bool(s and s["rank"] <= settings.retrieval_candidate_k and s["score"] >= settings.semantic_score_threshold)
        in_keyword_pool = bool(k and k <= settings.retrieval_candidate_k)
        final_rank = final_ids.index(doc_id) + 1 if doc_id in final_ids else None
        per_doc[doc_id] = {
            "semantic_rank": s["rank"] if s else None, "semantic_score": s["score"] if s else None,
            "keyword_rank": k, "in_candidate_pool": in_semantic_pool or in_keyword_pool,
            "pool_source": "semantic" if in_semantic_pool else "keyword" if in_keyword_pool else None,
            "final_rank": final_rank,
            "dropped_by_rerank": (in_semantic_pool or in_keyword_pool) and final_rank is None,
        }
    return {
        "query": query,
        "final_ids": final_ids,
        "final_via": [h["source"] for h in final],
        "final_distinct_docs": len(set(final_ids)),
        "top_semantic_score": round(semantic[0]["score"], 4) if semantic else None,
        "intended": per_doc,
        "hit_any": any(v["final_rank"] for v in per_doc.values()),
        "hit_all": all(v["final_rank"] for v in per_doc.values()),
    }


def detect_acts(question, acts):
    """Non-oracle: Acts named in the question text, by full title (without year) or common abbreviation."""
    q = f" {norm(question)} "
    found = {}
    for act_id, info in acts.items():
        title = re.sub(r"\s\d{4}$", "", norm(re.sub(r"^\s*the\s+", "", info["title"] or "", flags=re.IGNORECASE))).strip()
        if len(title) >= 10 and f" {title} " in q:
            found[act_id] = title
    for pattern, act_id in ABBREVIATIONS:
        if act_id in acts and re.search(pattern, question, re.IGNORECASE):
            found.setdefault(act_id, act_id)
    return [a for a, t in found.items() if not any(t != o and t in o for o in found.values())]


def structured_resolution(question, acts, meta):
    """Non-oracle: Act names + section numbers in the question resolved directly to document ids."""
    detected = detect_acts(question, acts)
    sections = SECTION_REF.findall(question)
    candidates = [make_statute_doc_id(a, s) for a in detected for s in sections]
    return {"detected_acts": detected, "section_numbers": sections, "resolved_doc_ids": [d for d in candidates if d in meta]}


def filtered_semantic(query, doc_ids, k=5):
    if not doc_ids:
        return []
    raw = get_vector_store().query(query, top_k=k * 3, where={"doc_id": {"$in": doc_ids}})
    ordered = []
    for hit in raw:
        doc_id = hit["metadata"]["doc_id"]
        if doc_id not in ordered:
            ordered.append(doc_id)
    return ordered[:k]


def source_filtered_semantic(query, source_type, k=5):
    ordered = []
    for hit in semantic_search(query, top_k=k * 3, source_type=source_type):
        if hit["doc_id"] not in ordered:
            ordered.append(hit["doc_id"])
    return ordered[:k]


def clean_case_title(title):
    return re.sub(r"\s+on\s+\d{1,2}\s+[A-Za-z]+,?\s+\d{4}\s*$", "", title or "").strip()


def query_variants(question, category, intended, meta):
    variants = [{"name": "original", "oracle": False, "query": question}]
    statutes = [meta[d] for d in intended if meta.get(d, {}).get("source_type") == "statute"]
    judgments = [(d, meta[d]) for d in intended if meta.get(d, {}).get("source_type") == "case_law"]
    q_norm = norm(question)

    if statutes:
        act_titles = list(dict.fromkeys(s["act_title"] for s in statutes))
        missing_titles = [t for t in act_titles if norm(re.sub(r",?\s*\d{4}\.?$", "", t)) not in q_norm]
        if missing_titles:
            variants.append({"name": "question+act_name", "oracle": True, "query": f"{question} {' '.join(missing_titles)}"})
        variants.append({"name": "question+section_number", "oracle": True,
                         "query": f"{question} " + " ".join(f"Section {s['section']}" for s in statutes)})
        variants.append({"name": "section_number+act_name", "oracle": True,
                         "query": "; ".join(f"Section {s['section']} of {s['act_title']}" for s in statutes)})
        variants.append({"name": "act+section+heading", "oracle": True,
                         "query": "; ".join(f"{s['act_title']} Section {s['section']} {s['heading'] or ''}".strip() for s in statutes)})
        if category == "old_new_law" and len(statutes) == 2:
            old, new = statutes
            variants.append({"name": "old_law+new_law_names", "oracle": True,
                             "query": f"{old['act_title']} Section {old['section']} corresponding provision {new['act_title']}"})
    for _, judgment in judgments:
        name = clean_case_title(judgment["title"])
        variants.append({"name": "case_name", "oracle": True, "query": name})
        variants.append({"name": "case_name+question", "oracle": True, "query": f"{name} {question}"})

    ordered_terms = []
    for token in re.findall(r"[a-z0-9]+", question.lower()):
        if token in question_tokens(question) and token not in ordered_terms:
            ordered_terms.append(token)
    variants.append({"name": "key_terms", "oracle": False, "query": " ".join(ordered_terms)})
    return variants


def mechanisms(question, category, intended, meta, acts):
    """Alternative retrieval mechanisms, run against the original question."""
    results = {}
    resolution = structured_resolution(question, acts, meta)
    results["structured_reference_resolution"] = {
        "oracle": False, **resolution,
        "found_intended": [d for d in intended if d in resolution["resolved_doc_ids"]],
    }
    detected_docs = [d for a in resolution["detected_acts"] for d in acts[a]["doc_ids"]]
    auto = filtered_semantic(question, detected_docs)
    results["act_filtered_semantic_auto_detected"] = {
        "oracle": False, "acts": resolution["detected_acts"], "top5": auto,
        "found_intended": [d for d in intended if d in auto],
    }
    oracle_acts = list(dict.fromkeys(meta[d]["act_id"] for d in intended if meta.get(d, {}).get("act_id")))
    if oracle_acts:
        oracle_docs = [d for a in oracle_acts for d in acts[a]["doc_ids"]]
        top = filtered_semantic(question, oracle_docs)
        results["act_filtered_semantic_oracle_act"] = {
            "oracle": True, "acts": oracle_acts, "top5": top, "found_intended": [d for d in intended if d in top],
        }
    if category == "old_new_law":
        expanded = []
        for doc_id in resolution["resolved_doc_ids"]:
            for link in meta[doc_id]["corresponds_to"]:
                if isinstance(link, dict) and link.get("act") and link.get("section"):
                    expanded.append(make_statute_doc_id(link["act"], link["section"]))
        results["mapping_expansion_from_resolved_reference"] = {
            "oracle": False, "starting_docs": resolution["resolved_doc_ids"], "mapped_docs": expanded,
            "found_intended": [d for d in intended if d in resolution["resolved_doc_ids"] + expanded],
        }
    if category in ("multiple_authorities", "case_law", "multiple_sections"):
        for source_type in ("statute", "case_law"):
            top = source_filtered_semantic(question, source_type)
            results[f"semantic_{source_type}_only_top5"] = {
                "oracle": False, "top5": top, "found_intended": [d for d in intended if d in top],
            }
    return results


def unmatched_quote_analysis(record, meta):
    retrieved = [normalize_text(d["text"]) for d in record["retrieved_context"]]
    rows = []
    for citation in record["teacher"]["raw_llm_citations"]:
        quote = citation.get("evidence_quote", "")
        nq = normalize_text(quote)
        if not nq or any(nq in passage for passage in retrieved):
            continue
        claimed = citation.get("doc_id")
        in_claimed = bool(meta.get(claimed)) and nq in normalize_text(meta[claimed]["text"])
        rows.append({
            "claimed_doc_id": claimed, "quote": quote,
            "found_in_claimed_document_full_text": in_claimed,
            "classification": "spans_or_outside_retrieved_chunk" if in_claimed else "not_verbatim_in_claimed_document",
        })
    return rows


def case_law_benchmark(meta, rng, sample_size=20):
    judgments = [
        (d, m) for d, m in sorted(meta.items())
        if m["source_type"] == "case_law" and len(m["text"] or "") > 3000 and re.search(r"\bvs?\.?\s", m["title"] or "")
    ]
    sample = rng.sample(judgments, min(sample_size, len(judgments)))
    rows = []
    for doc_id, m in sample:
        text = m["text"]
        sentences = [s.strip() for s in re.split(r"(?<=[.])\s+", text[len(text) // 3: 2 * len(text) // 3]) if 25 <= len(s.split()) <= 45]
        patterns = {"exact_case_name": clean_case_title(m["title"]), "title_as_stored": m["title"]}
        if sentences:
            patterns["verbatim_sentence_from_judgment"] = rng.choice(sentences)
        for pattern, query in patterns.items():
            stage = stage_ranks(query, [doc_id])
            info = stage["intended"][doc_id]
            rows.append({"doc_id": doc_id, "pattern": pattern, "query": query[:200], "final_rank": info["final_rank"],
                         "semantic_rank": info["semantic_rank"], "keyword_rank": info["keyword_rank"],
                         "dropped_by_rerank": info["dropped_by_rerank"]})
    return rows


def citation_benchmark(meta, rng, sample_size=10):
    citation_re = re.compile(r"\(\d{4}\)\s*\d+\s*SCC\s*\d+")
    counts = Counter()
    for m in meta.values():
        if m["source_type"] == "case_law":
            counts.update(set(" ".join(c.split()) for c in citation_re.findall(m["text"] or "")))
    citations = sorted(counts)
    rows = []
    for citation in rng.sample(citations, min(sample_size, len(citations))):
        holders = {d for d, m in meta.items() if m["source_type"] == "case_law" and citation in " ".join((m["text"] or "").split())}
        final = hybrid_search(citation, top_k=settings.default_top_k)
        final_ids = [h["doc_id"] for h in final]
        rows.append({"citation": citation, "judgments_containing_it": len(holders),
                     "final_docs_containing_it": sum(1 for d in final_ids if d in holders), "final_ids": final_ids})
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    meta, acts = load_metadata()
    questions = read_jsonl(PILOT / "questions.jsonl")
    records = latest_by_id(read_jsonl(PILOT / "teacher_records.jsonl"))

    all_examples = []
    for q in questions:
        record = records[q["id"]]
        intended = q["seed"]["doc_ids"]
        stage = stage_ranks(q["question"], intended)
        pilot_ids = [d["doc_id"] for d in record["retrieved_context"]]
        all_examples.append({
            "id": q["id"], "category": q["category"], "status": record["status"], "reasons": record["status_reasons"],
            "intended": intended, "pilot_retrieved_ids": pilot_ids,
            "pilot_intended_ranks": {d: (pilot_ids.index(d) + 1 if d in pilot_ids else None) for d in intended},
            "rerun": stage,
            "rerun_matches_pilot": stage["final_ids"] == pilot_ids,
        })
        print(f"[all50] {q['id']} {q['category']:22} pilot_hit={any(d in pilot_ids for d in intended)!s:5} "
              f"rerun_hit={stage['hit_any']!s:5} ranks={[(v['semantic_rank'], v['keyword_rank'], v['final_rank']) for v in stage['intended'].values()]}", flush=True)

    review = []
    for q in questions:
        record = records[q["id"]]
        if record["status"] != "needs_review":
            continue
        intended = q["seed"]["doc_ids"]
        variants = []
        for variant in query_variants(q["question"], q["category"], intended, meta):
            stage = stage_ranks(variant["query"], intended)
            variants.append({**variant, "hit_any": stage["hit_any"], "hit_all": stage["hit_all"],
                             "intended": stage["intended"], "final_ids": stage["final_ids"]})
        review.append({
            "id": q["id"], "category": q["category"], "question": q["question"], "intended": intended,
            "variants": variants,
            "mechanisms": mechanisms(q["question"], q["category"], intended, meta, acts),
            "unmatched_quotes": unmatched_quote_analysis(record, meta),
        })
        print(f"[review] {q['id']} " + " | ".join(f"{v['name']}={'Y' if v['hit_any'] else 'n'}" for v in variants), flush=True)

    case_rows = case_law_benchmark(meta, rng)
    citation_rows = citation_benchmark(meta, rng)

    output = {"all_examples": all_examples, "review_examples": review, "case_law_benchmark": case_rows,
              "citation_benchmark": citation_rows,
              "settings": {"default_top_k": settings.default_top_k, "retrieval_candidate_k": settings.retrieval_candidate_k,
                           "semantic_score_threshold": settings.semantic_score_threshold,
                           "max_chunks_per_document": settings.max_chunks_per_document, "rerank_enabled": settings.rerank_enabled}}
    (OUT / "probe_results.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print("saved", OUT / "probe_results.json")


if __name__ == "__main__":
    main()
