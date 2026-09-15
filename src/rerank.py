"""
Context selection: decides which retrieved chunks reach the LLM. Runs between hybrid_search()'s
retrievers and prompt assembly in rag_chain.py.

Default (RERANK_STRATEGY=rrf) — Reciprocal Rank Fusion. Each retriever (semantic chunk search,
keyword/BM25 document search, explicit legal-reference lookup, old/new code mapping) returns its own
ranked list. Their scores are not on one scale (cosine similarity, BM25, a deterministic lookup), so
ranks are fused rather than scores:

    rrf(document) = sum over the lists containing it of 1 / (k + rank)     rank starts at 1, k = RRF_K

A document found by several retrievers accumulates contributions, and a strong keyword-only match is
no longer capped below every semantic hit. Ties break deterministically: best semantic similarity,
then best rank in any single list, then doc_id. search.py reserves slots for evidence the query
explicitly requires, fills the rest in fused order and gives each document one evidence block.

RERANK_STRATEGY=weighted keeps the previous scoring (0.75 x semantic similarity + 0.25 x query-word
overlap) for comparison and rollback.
"""
import re
from typing import Dict, List, Optional, Sequence

from config import settings
from logging_config import get_logger

logger = get_logger("rerank")

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+")


def rrf_order(
    rankings: Dict[str, Sequence[str]], k: Optional[int] = None, semantic_scores: Optional[Dict[str, float]] = None,
) -> List[Dict]:
    """rankings: retriever name -> doc_ids, best first (repeats are ignored after the first).
    Returns one entry per document, best first: {doc_id, rrf_score, retrieval_ranks}."""
    k = settings.rrf_k if k is None else k
    semantic_scores = semantic_scores or {}
    fused: Dict[str, Dict] = {}
    for name, doc_ids in rankings.items():
        rank = 0
        seen = set()
        for doc_id in doc_ids:
            if not doc_id or doc_id in seen:
                continue
            seen.add(doc_id)
            rank += 1
            entry = fused.setdefault(doc_id, {"doc_id": doc_id, "rrf_score": 0.0, "retrieval_ranks": {}})
            entry["rrf_score"] += 1.0 / (k + rank)
            entry["retrieval_ranks"][name] = rank

    def order(entry):
        semantic = semantic_scores.get(entry["doc_id"])
        return (
            -round(entry["rrf_score"], 12),
            -(semantic if semantic is not None else -1.0),
            min(entry["retrieval_ranks"].values()),
            entry["doc_id"],
        )

    return sorted(fused.values(), key=order)


def _query_terms(query: str) -> List[str]:
    return [t for t in _TOKEN_PATTERN.findall(query.lower()) if len(t) > 2]


def _keyword_overlap_score(query_terms: List[str], text: str) -> float:
    if not text or not query_terms:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for t in query_terms if t in text_lower)
    return hits / len(query_terms)


def weighted_rerank(hits: List[Dict], query: str, top_k: int = 5, max_per_doc: int = None) -> List[Dict]:
    """Previous strategy. hits: dicts with at least 'doc_id', 'text', 'score' (semantic similarity in
    [0,1], or None for keyword-only hits, which therefore score at most 0.25)."""
    if not hits:
        return []

    max_per_doc = max_per_doc if max_per_doc is not None else settings.max_chunks_per_document
    query_terms = _query_terms(query)

    scored = []
    for h in hits:
        semantic_score = h.get("score") if h.get("score") is not None else 0.0
        kw_score = _keyword_overlap_score(query_terms, h.get("text", ""))
        combined = 0.75 * semantic_score + 0.25 * kw_score
        scored.append({**h, "rerank_score": combined})

    scored.sort(key=lambda h: h["rerank_score"], reverse=True)

    doc_counts: Dict[str, int] = {}
    selected = []
    for h in scored:
        doc_id = h.get("doc_id")
        if doc_counts.get(doc_id, 0) >= max_per_doc:
            continue
        selected.append(h)
        doc_counts[doc_id] = doc_counts.get(doc_id, 0) + 1
        if len(selected) >= top_k:
            break

    logger.debug("Reranked %d hits -> %d selected (top_k=%d, max_per_doc=%d)", len(hits), len(selected), top_k, max_per_doc)
    return selected


# Earlier name of the weighted strategy, kept so existing imports keep working.
rerank = weighted_rerank
