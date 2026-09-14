"""
Hybrid retrieval: ChromaDB semantic search (via vector_store.py, OpenAI
embeddings) merged with SQLite FTS5 keyword search (via db.py), followed by
a lightweight reranking/context-selection pass (rerank.py).

`source_type` restricts both halves to one kind of document (e.g. only
statutes), which is what the retrieval-only statute/case search modes use.
`on_stage` reports real pipeline steps as they happen, for progress UIs.

No UI framework dependency on purpose — this module is called from the API,
the Streamlit app, the evaluation harness, and scripts alike.
"""
from typing import Callable, Dict, List, Optional

from config import settings
from db import get_document, search_keyword
from logging_config import get_logger
from rerank import rerank
from vector_store import get_vector_store

logger = get_logger("search")

StageCallback = Callable[[str, str, Optional[Dict]], None]


def _noop_stage(stage: str, status: str, detail: Optional[Dict] = None):
    pass


def semantic_search(
    query: str, top_k: int = None, threshold: float = None, source_type: Optional[str] = None,
) -> List[Dict]:
    top_k = top_k or settings.retrieval_candidate_k
    threshold = settings.semantic_score_threshold if threshold is None else threshold
    where = {"source_type": source_type} if source_type else None

    store = get_vector_store()
    raw_hits = store.query(query, top_k=top_k, where=where)

    hits = []
    for h in raw_hits:
        if h["score"] < threshold:
            continue
        meta = h["metadata"] or {}
        hits.append({
            "doc_id": meta.get("doc_id"), "title": meta.get("title"),
            "court": meta.get("court"), "date": meta.get("date"),
            "section": meta.get("section"), "source_type": meta.get("source_type"),
            "file_name": meta.get("file_name"), "page_start": meta.get("page_start"),
            "page_end": meta.get("page_end"), "chunk_id": meta.get("chunk_id"),
            "text": h["text"], "score": h["score"], "source": "semantic",
        })
    logger.debug("Semantic search: %d hit(s) above threshold %.2f", len(hits), threshold)
    return hits


def _keyword_hit_to_context_hit(kw: Dict) -> Dict:
    """The original implementation left keyword-only hits with empty text,
    which meant they were silently dropped by build_context() and could
    never actually be cited. Pull the document's stored full_text so a
    keyword match contributes real, citable content too."""
    doc = get_document(kw["doc_id"])
    text = ""
    if doc and doc.get("full_text"):
        text = doc["full_text"][: settings.chunk_target_chars]
    return {
        "doc_id": kw["doc_id"], "title": kw["title"], "court": kw["court"],
        "date": kw["date"], "section": "keyword_match", "source_type": kw.get("source_type"),
        "file_name": "", "page_start": None, "page_end": None, "chunk_id": None,
        "text": text, "score": None, "source": "keyword",
    }


def hybrid_search(
    query: str, top_k: int = None, source_type: Optional[str] = None, on_stage: Optional[StageCallback] = None,
) -> List[Dict]:
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

    seen_doc_ids = {h["doc_id"] for h in semantic_hits}
    merged = list(semantic_hits)
    for kh in keyword_hits:
        if kh["doc_id"] not in seen_doc_ids:
            merged.append(_keyword_hit_to_context_hit(kh))
            seen_doc_ids.add(kh["doc_id"])

    emit("ranking", "started", {"candidates": len(merged)})
    if settings.rerank_enabled:
        final_results = rerank(merged, query, top_k=top_k)
    else:
        final_results = merged[:top_k]
    emit("ranking", "done", {
        "selected": len(final_results),
        "statutes": sum(1 for r in final_results if r.get("source_type") == "statute"),
        "judgments": sum(1 for r in final_results if r.get("source_type") == "case_law"),
    })

    logger.info("hybrid_search(%r): %d final result(s)", query[:80], len(final_results))
    for r in final_results:
        logger.debug(" - %s | %s (%s)", r["doc_id"], r["title"], r["source"])

    return final_results
