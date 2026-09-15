"""
Hybrid retrieval: ChromaDB semantic search (via vector_store.py, OpenAI embeddings), SQLite FTS5
keyword search (via db.py) and legal-reference planning (via legal_references.py), followed by
context selection (rerank.py).

With the default RERANK_STRATEGY=rrf, context selection has two stages:

1. Evidence requirements. plan_retrieval() reads the query: sections it names unambiguously, their
   stored old/new counterparts when the query also names the counterpart's Act, and — when the query
   asks how courts have treated a point — one judgment. Up to top_k - MIN_DISCOVERY_SLOTS of these are
   reserved in the final context (at least one of each kind first, then in order of mention), so a
   named section cannot be outranked out of the evidence.
2. Discovery. The remaining slots go to Reciprocal Rank Fusion over independent rankings: semantic,
   keyword/BM25, explicit references, mapped provisions, and a sub-query (the query with its reference
   text removed) for the other authorities it needs. Every semantic view of the same query text — the
   global search, the search within the one Act a query is about, the judgments-only search — is merged
   into ONE ranking ordered by similarity score, so a filtered view never counts the same signal twice.

Each selected document contributes one evidence block. A statute section short enough
(SECTION_CONTEXT_MAX_CHARS) is given whole, so a definition in its third chunk is not cut off; a longer
section contributes its SECTION_CONTEXT_CHUNKS chunks most similar to the query; a judgment contributes
its most similar chunk.

RERANK_STRATEGY=weighted reproduces the previous semantic + keyword score mixing (no planning).

`source_type` restricts retrieval to one kind of document (e.g. only statutes), which is what the
retrieval-only statute/case search modes use. `on_stage` reports real pipeline steps as they happen,
for progress UIs.

No UI framework dependency on purpose — this module is called from the API,
the Streamlit app, the evaluation harness, and scripts alike.
"""
import re
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

from config import settings
from db import get_document, search_keyword
from legal_references import (
    LegalReference, MappedProvision, RetrievalPlan, act_doc_ids, expand_mappings, find_references, plan_retrieval,
)
from logging_config import get_logger
from rerank import rrf_order, weighted_rerank
from vector_store import get_vector_store

logger = get_logger("search")

StageCallback = Callable[[str, str, Optional[Dict]], None]

# The retriever named in a fused hit's "source": the first of these that ranked the document.
RETRIEVER_PRIORITY = ("semantic", "keyword", "reference", "mapping", "subquery_semantic")
REQUIREMENT_ORDER = ("explicit_reference", "mapped_counterpart", "case_law_authority")
_CHUNK_INDEX = re.compile(r"_chunk(\d+)$")


def _noop_stage(stage: str, status: str, detail: Optional[Dict] = None):
    pass


def _vector_hit(raw: Dict, source: str) -> Dict:
    meta = raw["metadata"] or {}
    return {
        "doc_id": meta.get("doc_id"), "title": meta.get("title"),
        "court": meta.get("court"), "date": meta.get("date"),
        "section": meta.get("section"), "source_type": meta.get("source_type"),
        "file_name": meta.get("file_name"), "page_start": meta.get("page_start"),
        "page_end": meta.get("page_end"), "chunk_id": meta.get("chunk_id"),
        "text": raw["text"], "score": raw["score"], "source": source,
    }


def semantic_search(
    query: str, top_k: int = None, threshold: float = None, source_type: Optional[str] = None,
) -> List[Dict]:
    top_k = top_k or settings.retrieval_candidate_k
    threshold = settings.semantic_score_threshold if threshold is None else threshold
    where = {"source_type": source_type} if source_type else None

    store = get_vector_store()
    raw_hits = store.query(query, top_k=top_k, where=where)

    hits = [_vector_hit(h, "semantic") for h in raw_hits if h["score"] >= threshold]
    logger.debug("Semantic search: %d hit(s) above threshold %.2f", len(hits), threshold)
    return hits


def best_chunks_for_documents(query: str, doc_ids: List[str], per_document: int = 1) -> Dict[str, List[Dict]]:
    """The chunks of each document most similar to `query` (no threshold), best first."""
    store = get_vector_store()
    best = {}
    for doc_id in doc_ids:
        raw = store.query(query, top_k=per_document, where={"doc_id": doc_id})
        if raw:
            best[doc_id] = [_vector_hit(h, "semantic") for h in raw]
    return best


def _document_hit(doc: Dict, source: str) -> Dict:
    """Context hit built from a whole stored document (first chunk_target_chars characters)."""
    return {
        "doc_id": doc["doc_id"], "title": doc["title"], "court": doc.get("court"),
        "date": doc.get("date"), "section": "keyword_match", "source_type": doc.get("source_type"),
        "file_name": "", "page_start": None, "page_end": None, "chunk_id": None,
        "text": (doc.get("full_text") or "")[: settings.chunk_target_chars], "score": None, "source": source,
    }


def _keyword_hit_to_context_hit(kw: Dict) -> Dict:
    """The original implementation left keyword-only hits with empty text,
    which meant they were silently dropped by build_context() and could
    never actually be cited. Pull the document's stored full_text so a
    keyword match contributes real, citable content too."""
    doc = get_document(kw["doc_id"])
    return _document_hit({**kw, "full_text": doc.get("full_text") if doc else ""}, "keyword")


def legal_reference_candidates(
    query: str, source_type: Optional[str] = None,
) -> Tuple[List[LegalReference], List[MappedProvision]]:
    """Explicit statute references in the query and their mapped old/new counterparts."""
    plan = retrieval_plan(query, source_type)
    return plan.references, plan.mapped


def retrieval_plan(query: str, source_type: Optional[str] = None) -> RetrievalPlan:
    """plan_retrieval() restricted to what the current settings and source_type allow."""
    try:
        plan = plan_retrieval(query, settings.mapping_max_per_reference, use_mapping=settings.mapping_lookup_enabled)
    except Exception:
        logger.exception("Legal reference planning failed for query=%r; continuing without it", query[:80])
        return RetrievalPlan()
    if not settings.reference_lookup_enabled or source_type == "case_law":
        plan.references, plan.mapped = [], []
        plan.requirements = [r for r in plan.requirements if r.reason == "case_law_authority"]
    if not settings.act_scope_enabled or source_type == "case_law":
        plan.act_scope = []
    if not settings.case_law_subquery_enabled or source_type == "statute":
        plan.needs_case_law = False
        plan.requirements = [r for r in plan.requirements if r.reason != "case_law_authority"]
    return plan


def _legacy_merge(semantic_hits: List[Dict], keyword_hits: List[Dict]) -> List[Dict]:
    seen_doc_ids = {h["doc_id"] for h in semantic_hits}
    merged = list(semantic_hits)
    for kh in keyword_hits:
        if kh["doc_id"] not in seen_doc_ids:
            merged.append(_keyword_hit_to_context_hit(kh))
            seen_doc_ids.add(kh["doc_id"])
    return merged


def _chunk_order(chunk_id: Optional[str]) -> int:
    match = _CHUNK_INDEX.search(chunk_id or "")
    return int(match.group(1)) if match else 0


def _evidence_block(query: str, doc_id: str, candidates: List[Dict]) -> Optional[Dict]:
    """One evidence block for a selected document (see module docstring)."""
    store = get_vector_store()
    stored = store.collection.get(where={"doc_id": doc_id}, include=["documents", "metadatas"])
    entries = sorted(zip(stored["ids"], stored["documents"], stored["metadatas"]), key=lambda e: _chunk_order(e[2].get("chunk_id")))
    if not entries:
        doc = get_document(doc_id)
        return {**_document_hit(doc, "keyword"), "chunk_ids": [], "context_span": "document_opening"} if doc else None

    ranked = sorted(candidates, key=lambda h: -(h.get("score") or 0))
    meta = entries[0][2]
    base = _vector_hit({"metadata": meta, "text": "", "score": ranked[0]["score"] if ranked else None}, "semantic")
    if len(entries) == 1:
        return {**base, "chunk_id": meta.get("chunk_id"), "chunk_ids": [meta.get("chunk_id")], "text": entries[0][1],
                "context_span": "full_section" if meta.get("source_type") == "statute" else "full_document"}

    if meta.get("source_type") == "statute":
        doc = get_document(doc_id)
        full_text = (doc or {}).get("full_text") or ""
        if full_text and len(full_text) <= settings.section_context_max_chars:
            best = ranked[0]["chunk_id"] if ranked else meta.get("chunk_id")
            return {**base, "chunk_id": best, "chunk_ids": [e[2].get("chunk_id") for e in entries], "text": full_text,
                    "context_span": "full_section"}
        wanted = max(1, settings.section_context_chunks)
    else:
        wanted = 1

    if len({h["chunk_id"] for h in ranked}) < wanted:
        extra = best_chunks_for_documents(query, [doc_id], per_document=wanted).get(doc_id, [])
        ranked = sorted({h["chunk_id"]: h for h in ranked + extra}.values(), key=lambda h: -(h.get("score") or 0))
    chosen = sorted(list({h["chunk_id"]: h for h in ranked}.values())[:wanted], key=lambda h: _chunk_order(h["chunk_id"]))
    if not chosen:
        chosen = [{"chunk_id": entries[0][2].get("chunk_id"), "text": entries[0][1], "score": None}]
    return {
        **base, "section": chosen[0].get("section") or meta.get("section"), "chunk_id": ranked[0]["chunk_id"] if ranked else chosen[0]["chunk_id"],
        "chunk_ids": [c["chunk_id"] for c in chosen], "text": "\n[…]\n".join(c["text"] for c in chosen),
        "context_span": "best_chunks" if len(chosen) > 1 else "chunk",
    }


def _fuse(
    query: str, top_k: int, source_type: Optional[str], semantic_hits: List[Dict], keyword_hits: List[Dict],
    plan: RetrievalPlan,
) -> Tuple[List[Dict], Dict]:
    store = get_vector_store()
    candidate_k = max(settings.retrieval_candidate_k, top_k)
    views: Dict[str, set] = defaultdict(set)  # semantic views (act_scope, case_law) that surfaced each document

    semantic_pool = list(semantic_hits)
    if plan.act_scope:
        ids = [doc_id for act_id in plan.act_scope for doc_id in act_doc_ids(act_id)]
        if ids:
            where = {"doc_id": ids[0]} if len(ids) == 1 else {"doc_id": {"$in": ids}}
            scoped = [_vector_hit(h, "semantic") for h in store.query(query, top_k=candidate_k, where=where)
                      if h["score"] >= settings.semantic_score_threshold]
            semantic_pool += scoped
            for hit in scoped:
                views[hit["doc_id"]].add("act_scope")
    sub_query = plan.residual_query if len(plan.residual_query.split()) >= 4 else query
    sub_pool: List[Dict] = []
    if plan.references and sub_query != query:
        sub_pool += semantic_search(sub_query, top_k=candidate_k, source_type=source_type)
    judgments: List[Dict] = []
    if plan.needs_case_law:
        judgments = semantic_search(sub_query, top_k=candidate_k, source_type="case_law")
        for hit in judgments:
            views[hit["doc_id"]].add("case_law")
        if sub_query == query:
            semantic_pool += judgments
        else:
            sub_pool += judgments

    def by_score(pool):
        unique = {hit["chunk_id"]: hit for hit in pool}
        return sorted(unique.values(), key=lambda h: (-h["score"], h["chunk_id"] or ""))

    semantic_ranked = by_score(semantic_pool)
    chunks: Dict[str, List[Dict]] = defaultdict(list)
    for hit in semantic_ranked:
        chunks[hit["doc_id"]].append(hit)
    best_scores = {doc_id: hits[0]["score"] for doc_id, hits in chunks.items()}
    rankings = {
        "semantic": [h["doc_id"] for h in semantic_ranked],
        "keyword": [h["doc_id"] for h in keyword_hits],
        "reference": [r.doc_id for r in plan.references],
        "mapping": [m.doc_id for m in plan.mapped],
    }
    if sub_pool:
        sub_ranked = by_score(sub_pool)
        rankings["subquery_semantic"] = [h["doc_id"] for h in sub_ranked]
        for hit in sub_ranked:
            if hit["doc_id"] not in best_scores:
                chunks[hit["doc_id"]].append(hit)
    judgment_ids = {h["doc_id"] for h in judgments}

    fused = rrf_order(rankings, k=settings.rrf_k, semantic_scores=best_scores)
    position = {entry["doc_id"]: index for index, entry in enumerate(fused)}
    entries = {entry["doc_id"]: entry for entry in fused}

    grouped: Dict[str, List[Tuple[str, object]]] = {name: [] for name in REQUIREMENT_ORDER}
    for requirement in plan.requirements:
        if requirement.reason == "case_law_authority":
            judgments_ranked = sorted((d for d in judgment_ids if d in position), key=position.get)
            if judgments_ranked:
                grouped[requirement.reason].append((judgments_ranked[0], requirement))
        elif requirement.doc_id in position:
            grouped[requirement.reason].append((requirement.doc_id, requirement))
    capacity = max(0, top_k - settings.min_discovery_slots)
    reserved: Dict[str, object] = {}
    for name in REQUIREMENT_ORDER:  # at least one requirement of each kind first
        for doc_id, requirement in grouped[name][:1]:
            if len(reserved) < capacity and doc_id not in reserved:
                reserved[doc_id] = requirement
    for name in REQUIREMENT_ORDER:  # then the rest, in order of mention
        for doc_id, requirement in grouped[name][1:]:
            if len(reserved) < capacity and doc_id not in reserved:
                reserved[doc_id] = requirement

    selected = list(reserved)
    for entry in fused:
        if len(selected) >= top_k:
            break
        if entry["doc_id"] not in reserved:
            selected.append(entry["doc_id"])
    selected.sort(key=position.get)

    results = []
    for doc_id in selected:
        block = _evidence_block(query, doc_id, chunks.get(doc_id, []))
        if block is None:
            continue
        entry = entries[doc_id]
        requirement = reserved.get(doc_id)
        block.update({
            "rrf_score": entry["rrf_score"], "rerank_score": entry["rrf_score"],
            "retrieval_ranks": dict(entry["retrieval_ranks"]),
            "source": next(name for name in RETRIEVER_PRIORITY if name in entry["retrieval_ranks"]),
            "found_by_views": sorted(views.get(doc_id, ())),
            "required_reason": getattr(requirement, "reason", None),
        })
        results.append(block)

    final_ids = {h["doc_id"] for h in results}
    has_judgment = any(h.get("source_type") == "case_law" for h in results)
    status = []
    for requirement in plan.requirements:
        if requirement.reason == "case_law_authority":
            satisfied = next((h["doc_id"] for h in results if h.get("source_type") == "case_law"), None) if has_judgment else None
        else:
            satisfied = requirement.doc_id if requirement.doc_id in final_ids else None
        status.append({"doc_id": requirement.doc_id, "reason": requirement.reason, "source_text": requirement.source_text,
                       "satisfied_by": satisfied, "reserved": any(r is requirement for r in reserved.values())})
    trace = {
        **plan.as_dict(),
        "ranking_list_sizes": {name: len(ids) for name, ids in rankings.items()},
        "reserved_capacity": capacity,
        "requirements_status": status,
        "missing_requirements": [s for s in status if not s["satisfied_by"]],
        "fused_top": [{"doc_id": e["doc_id"], "rrf_score": round(e["rrf_score"], 6), "retrieval_ranks": e["retrieval_ranks"]}
                      for e in fused[:30]],
    }
    return results, trace


def hybrid_search_with_plan(
    query: str, top_k: int = None, source_type: Optional[str] = None, on_stage: Optional[StageCallback] = None,
) -> Tuple[List[Dict], Dict]:
    """hybrid_search() plus a trace of the evidence requirements found and whether each was met."""
    top_k = top_k or settings.default_top_k
    candidate_k = max(settings.retrieval_candidate_k, top_k)
    emit = on_stage or _noop_stage

    emit("semantic", "started", {})
    semantic_hits = semantic_search(query, top_k=candidate_k, source_type=source_type)
    emit("semantic", "done", {"passages": len(semantic_hits)})

    emit("keyword", "started", {})
    keyword_hits = search_keyword(query, limit=candidate_k, source_type=source_type)
    emit("keyword", "done", {"documents": len(keyword_hits)})
    logger.debug("Keyword search: %d hit(s)", len(keyword_hits))

    strategy = settings.rerank_strategy.lower()
    fusing = settings.rerank_enabled and strategy == "rrf"
    plan = retrieval_plan(query, source_type) if fusing else RetrievalPlan()

    emit("ranking", "started", {
        "candidates": len({h["doc_id"] for h in semantic_hits} | {h["doc_id"] for h in keyword_hits}),
        "references": len(plan.references), "required": len(plan.requirements),
    })
    trace: Dict = {}
    if fusing:
        final_results, trace = _fuse(query, top_k, source_type, semantic_hits, keyword_hits, plan)
    elif settings.rerank_enabled:
        if strategy != "weighted":
            logger.warning("Unknown RERANK_STRATEGY=%r; using 'weighted'", settings.rerank_strategy)
        final_results = weighted_rerank(_legacy_merge(semantic_hits, keyword_hits), query, top_k=top_k)
    else:
        final_results = _legacy_merge(semantic_hits, keyword_hits)[:top_k]
    emit("ranking", "done", {
        "selected": len(final_results),
        "statutes": sum(1 for r in final_results if r.get("source_type") == "statute"),
        "judgments": sum(1 for r in final_results if r.get("source_type") == "case_law"),
    })

    logger.info("hybrid_search(%r): %d final result(s)", query[:80], len(final_results))
    for r in final_results:
        logger.debug(" - %s | %s (%s)", r["doc_id"], r["title"], r["source"])
    return final_results, trace


def hybrid_search(
    query: str, top_k: int = None, source_type: Optional[str] = None, on_stage: Optional[StageCallback] = None,
) -> List[Dict]:
    return hybrid_search_with_plan(query, top_k=top_k, source_type=source_type, on_stage=on_stage)[0]
