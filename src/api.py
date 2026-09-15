"""
HTTP API for the IndianLawGPT frontend.

A thin transport layer over the existing pipeline modules — rag_chain
(research answers), search (retrieval-only search), db (documents, acts,
mappings, corpus stats). No retrieval, generation or verification logic lives
here, so the API, the Streamlit POC and the evaluation harness all exercise
exactly the same pipeline.

Run from src/:
    uvicorn api:app --port 8010 --reload
"""
import html
import json
import queue
import re
import threading
import time
from typing import Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import settings
from db import get_corpus_stats, get_document, get_documents_brief, list_act_sections, list_mapped_acts
from ingest_statutes import make_statute_doc_id
from logging_config import get_logger
from engines import engine_status, run_engine
from rag_chain import answer_question
from search import hybrid_search
from vector_store import get_vector_store

logger = get_logger("api")

TOP_K_BY_MODE = {"research": 5, "quick": 4}
KEEPALIVE_SECONDS = 10
STATS_TTL_SECONDS = 300
MAX_HIGHLIGHT_QUOTES = 12
_WORD = re.compile(r"\w+")

app = FastAPI(title="IndianLawGPT API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


EngineKey = Literal["claude", "lora_qwen", "qwen"]


class ResearchRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    mode: Literal["research", "quick"] = "research"
    # Answer engine (engines.py). Omitted: the configured LLM_PROVIDER, exactly as before.
    engine: Optional[EngineKey] = None
    # Reuse a frozen evidence bundle so a second engine answers from the identical evidence.
    evidence_id: Optional[str] = Field(default=None, max_length=64)


class AnswerRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    model: EngineKey = "claude"
    mode: Literal["research", "quick"] = "research"
    evidence_id: Optional[str] = Field(default=None, max_length=64)


def _readable(text):
    """Scraped judgments store HTML entities (&quot;, &amp;, &#x27;) literally. Decode them for
    display; stored text and embeddings are left untouched."""
    return html.unescape(text) if isinstance(text, str) else text


def _parse_metadata(raw) -> Dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _document_summary(row: Dict) -> Dict:
    meta = _parse_metadata(row.get("metadata_json"))
    summary = {
        "doc_id": row["doc_id"],
        "title": _readable(row["title"]),
        "source_type": row["source_type"],
        "court": row.get("court") or None,
        "date": row.get("date") or None,
        "judges": [j.strip() for j in (row.get("judges") or "").split(",") if j.strip()],
        "file_name": row.get("file_name") or None,
    }
    if row["source_type"] == "statute":
        summary["statute"] = {
            "act_id": meta.get("act_id"),
            "act_title": meta.get("act_title"),
            "act_long_title": meta.get("act_long_title"),
            "act_year": meta.get("act_year"),
            "act_number": meta.get("act_number"),
            "section_number": meta.get("section_number"),
            "section_heading": meta.get("section_heading"),
            "enforcement_date": meta.get("enforcement_date"),
            "ministry": meta.get("ministry"),
            "source_url": meta.get("source_url") or row.get("file_name") or None,
            "has_correspondences": bool(meta.get("corresponds_to")),
        }
    return summary


def _attach_documents(items: List[Dict]) -> List[Dict]:
    rows = get_documents_brief(item["doc_id"] for item in items)
    summaries = {row["doc_id"]: _document_summary(row) for row in rows}
    for item in items:
        item["document"] = summaries.get(item["doc_id"])
    return items


def _find_highlights(text: str, quotes: List[str]) -> List[Dict]:
    """Locate each quote in the document, tolerant of punctuation and whitespace
    differences — the same leniency the citation mapper uses to match quotes."""
    spans = []
    for quote in quotes[:MAX_HIGHLIGHT_QUOTES]:
        tokens = _WORD.findall(quote or "")
        if len(tokens) < 3:
            continue
        pattern = re.compile(r"\W+".join(re.escape(t) for t in tokens), re.IGNORECASE)
        match = pattern.search(text)
        if match:
            spans.append({"quote": quote, "start": match.start(), "end": match.end()})
    spans.sort(key=lambda s: s["start"])
    return spans


def _correspondences(meta: Dict, include_text: bool = False) -> List[Dict]:
    entries = [c for c in (meta.get("corresponds_to") or []) if isinstance(c, dict)]
    target_ids = [
        make_statute_doc_id(c["act"], c["section"]) if c.get("act") and c.get("section") else None
        for c in entries
    ]
    rows = {
        row["doc_id"]: row
        for row in get_documents_brief((t for t in target_ids if t), include_text=include_text)
    }
    resolved = []
    for entry, target_id in zip(entries, target_ids):
        row = rows.get(target_id) if target_id else None
        resolved.append({
            "direction": entry.get("direction"),
            "relation": entry.get("relation"),
            "score": entry.get("score"),
            "act_id": entry.get("act"),
            "section_number": entry.get("section"),
            "official_url": entry.get("url"),
            "document": _document_summary(row) if row else None,
            "full_text": _readable(row.get("full_text")) if (row and include_text) else None,
        })
    return resolved


def _readable_citation(citation: Dict) -> Dict:
    citation["excerpt"] = _readable(citation.get("excerpt"))
    citation["passages"] = [_readable(p) for p in citation.get("passages", [])]
    citation["quotes"] = [_readable(q) for q in citation.get("quotes", [])]
    return citation


def _citation_check(result: Dict, citations: List[Dict]) -> Dict:
    """What the deterministic citation check did with the model's proposed citations: quotations matched to the
    retrieved evidence, quotations rejected (not found in the evidence, so their citations were dropped), and
    sources verified against the database. Reported, never repaired."""
    proposed = [c for c in result.get("extracted_evidence") or [] if isinstance(c, dict)]
    mapped_quotes = {quote for citation in result.get("citations") or [] for quote in citation.get("quotes") or []}
    rejected = [
        {"doc_id": c.get("doc_id") or None, "quote": _readable(c.get("evidence_quote") or "")}
        for c in proposed if (c.get("evidence_quote") or "") not in mapped_quotes
    ]
    return {
        "proposed": len(proposed),
        "matched": len(proposed) - len(rejected),
        "rejected": len(rejected),
        "rejected_quotes": rejected[:10],
        "sources": len(citations),
        "sources_verified": sum(1 for c in citations if c.get("verified")),
        "sources_unverified": len(result.get("unverified") or []),
    }


def _public_result(result: Dict, question: str) -> Dict:
    citations = [_readable_citation(c) for c in result.get("citations") or []]
    retrieved = result.get("retrieved_documents") or []
    for document in retrieved:
        document["excerpt"] = _readable(document.get("excerpt"))
    return {
        "citation_check": _citation_check(result, citations),
        "question": question,
        "mode": result.get("mode"),
        "answer_markdown": _readable(result.get("answer_markdown") or result.get("clean_answer") or ""),
        "citations": _attach_documents(citations),
        "retrieved_documents": _attach_documents(retrieved),
        "verified_count": len(result.get("verified") or []),
        "unverified": result.get("unverified") or [],
        "unmatched_citations": result.get("unmatched_citations", 0),
        "accuracy_note": result.get("accuracy_note"),
        "error": result.get("error"),
        "models": {
            "llm": (result.get("engine") or {}).get("model") or settings.llm_model, "embedding": settings.embedding_model,
        },
        "engine": result.get("engine"),
        "evidence": result.get("evidence"),
        "completed_at": time.time(),
    }


def _run(question: str, mode: str, engine: Optional[str], evidence_id: Optional[str], on_stage=None) -> Dict:
    if engine is None:
        return answer_question(question, top_k=TOP_K_BY_MODE[mode], on_stage=on_stage, mode=mode)
    return run_engine(question, engine, top_k=TOP_K_BY_MODE[mode], mode=mode, evidence_id=evidence_id, on_stage=on_stage)


def _sse(event: str, data: Dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/health")
def health():
    return {"status": "ok"}


_stats_cache: Dict = {"value": None, "at": 0.0}


@app.get("/api/stats")
def stats():
    now = time.time()
    if _stats_cache["value"] is None or now - _stats_cache["at"] > STATS_TTL_SECONDS:
        value = get_corpus_stats()
        try:
            value["passages"] = get_vector_store().collection.count()
        except Exception:
            logger.exception("Could not count vector store passages")
            value["passages"] = None
        value["models"] = {"llm": settings.llm_model, "embedding": settings.embedding_model}
        _stats_cache.update(value=value, at=now)
    return _stats_cache["value"]


@app.post("/api/research")
def research(request: ResearchRequest):
    """Streams Server-Sent Events: `stage` as each real pipeline step starts or
    finishes, then exactly one `result` (or `error`)."""
    question = request.question.strip()
    events: "queue.Queue" = queue.Queue()
    done = object()

    def on_stage(stage: str, status: str, detail: Dict):
        events.put(("stage", {"stage": stage, "status": status, "detail": detail, "at": time.time()}))

    def worker():
        try:
            result = _run(question, request.mode, request.engine, request.evidence_id, on_stage=on_stage)
            events.put(("result", _public_result(result, question)))
        except Exception:
            logger.exception("Research request failed for question=%r", question)
            events.put(("error", {"message": "The research pipeline failed unexpectedly. Please try again."}))
        finally:
            events.put(done)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        yield _sse("accepted", {"question": question, "mode": request.mode})
        while True:
            try:
                item = events.get(timeout=KEEPALIVE_SECONDS)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if item is done:
                break
            yield _sse(*item)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/answer")
def answer(request: AnswerRequest):
    """Non-streaming answer from one engine: retrieve (or reuse frozen evidence) → generate → validate →
    map → verify. The response's `engine.evidence_id` can be passed back to answer with another engine
    from the identical evidence. An unavailable engine fails with its own message; there is no fallback."""
    question = request.question.strip()
    try:
        result = _run(question, request.mode, request.model, request.evidence_id)
    except Exception:
        logger.exception("Answer request failed for question=%r", question)
        raise HTTPException(status_code=500, detail="The research pipeline failed unexpectedly. Please try again.")
    return _public_result(result, question)


@app.get("/api/engines")
def engines():
    """Answer engines and whether each is reachable right now (no generation is performed)."""
    return {"engines": engine_status()}


@app.get("/api/search")
def search(
    q: str = Query(min_length=2, max_length=500),
    source_type: Literal["statute", "case_law"] = Query("statute", alias="type"),
    limit: int = Query(12, ge=1, le=30),
):
    """Retrieval only — no LLM call. Same hybrid search the research pipeline uses,
    restricted to one source type, one row per document."""
    started = time.perf_counter()
    try:
        hits = hybrid_search(q, top_k=limit * 2, source_type=source_type)
    except Exception:
        logger.exception("Search failed for q=%r", q)
        raise HTTPException(status_code=503, detail="Search is temporarily unavailable.")

    results: Dict[str, Dict] = {}
    for hit in hits:
        if hit["doc_id"] in results or len(results) >= limit:
            continue
        results[hit["doc_id"]] = {
            "doc_id": hit["doc_id"], "title": _readable(hit["title"]), "excerpt": _readable(hit["text"]),
            "score": hit.get("score"), "matched_via": hit["source"],
        }
    return {
        "query": q,
        "type": source_type,
        "results": _attach_documents(list(results.values())),
        "took_ms": round((time.perf_counter() - started) * 1000),
    }


@app.get("/api/documents/{doc_id}")
def document(doc_id: str, quote: List[str] = Query(default=[])):
    row = get_document(doc_id)
    if row is None:
        raise HTTPException(status_code=404, detail="This source is not in the IndianLawGPT database.")
    meta = _parse_metadata(row.get("metadata_json"))
    text = _readable(row["full_text"])
    payload = {
        **_document_summary(row),
        "full_text": text,
        "highlights": _find_highlights(text, [_readable(q) for q in quote]),
    }
    if row["source_type"] == "statute":
        payload["correspondences"] = _correspondences(meta)
    return payload


@app.get("/api/acts/{act_id}/sections")
def act_sections(act_id: str):
    act = list_act_sections(act_id)
    if act is None:
        raise HTTPException(status_code=404, detail="This Act is not in the IndianLawGPT database.")
    return act


@app.get("/api/law-map/acts")
def law_map_acts():
    return {"acts": list_mapped_acts()}


@app.get("/api/law-map")
def law_map(act: str = Query(min_length=1, max_length=120), section: str = Query(min_length=1, max_length=20)):
    row = get_document(make_statute_doc_id(act.strip().lower(), section.strip()))
    if row is None or row["source_type"] != "statute":
        raise HTTPException(status_code=404, detail=f"Section {section.strip()} was not found in this Act.")
    meta = _parse_metadata(row.get("metadata_json"))
    return {
        "source": {**_document_summary(row), "full_text": _readable(row["full_text"])},
        "correspondences": _correspondences(meta, include_text=True),
    }
