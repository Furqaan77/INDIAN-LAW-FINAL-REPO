"""
Context selection: combines the semantic similarity score with a cheap
lexical-overlap signal (no extra API/model call), then caps how many chunks
any single document can contribute so the LLM's context window isn't
dominated by one long document. This runs between hybrid_search() and
prompt assembly in rag_chain.py.

Kept deliberately simple (no cross-encoder) for this POC — swap in a real
reranker later by replacing rerank() without changing its call sites.
"""
import re
from typing import Dict, List

from config import settings
from logging_config import get_logger

logger = get_logger("rerank")

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+")


def _query_terms(query: str) -> List[str]:
    return [t for t in _TOKEN_PATTERN.findall(query.lower()) if len(t) > 2]


def _keyword_overlap_score(query_terms: List[str], text: str) -> float:
    if not text or not query_terms:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for t in query_terms if t in text_lower)
    return hits / len(query_terms)


def rerank(hits: List[Dict], query: str, top_k: int = 5, max_per_doc: int = None) -> List[Dict]:
    """hits: list of dicts with at least 'doc_id', 'text', 'score' (semantic
    similarity in [0,1] or None for keyword-only hits)."""
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
