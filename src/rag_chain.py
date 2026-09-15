"""
RAG Chain — orchestrates retrieval and LLM generation.

Generation is delegated to llm_provider.py (Anthropic Claude by default).
The LLM is never trusted to emit a citation directly: it returns a Markdown
answer with inline [n] markers plus a citations array of
{doc_id, evidence_quote}. This module deterministically maps each
evidence_quote back to the retrieved chunk it actually came from, taking
that chunk's own doc_id from metadata — never the doc_id the model claims.
Markers are renumbered to the resulting sources, and a marker whose quote
matched no retrieved text is dropped. The mapped doc_ids are appended as
[SOURCE: id] tokens and handed to citation_verifier.py, the final gate
against a citation that doesn't exist in the database.
"""
import hashlib
import re
import time
from collections import OrderedDict

import instrumentation
from citation_verifier import verify_citations
from config import settings
from llm_provider import get_llm_provider
from logging_config import get_logger
from search import hybrid_search_with_plan

logger = get_logger("rag_chain")

SYSTEM_PROMPT = """You are a legal research assistant for Indian law. You answer ONLY using the \
source excerpts provided below (statutory provisions, case judgments and other legal documents). \
Do not use any outside knowledge or cases/statutes you recall from training.

CRITICAL RULES:
1. DO NOT state a broad legal conclusion unless the provided excerpts explicitly state that exact conclusion.
2. The mere presence of a source in the database does NOT mean it supports a specific legal interpretation. You must read the actual text of the excerpt.
3. Your answer must be grounded ONLY in the facts and reasoning directly present in the provided excerpts.
4. If the retrieved excerpts conflict, are ambiguous, or do not clearly support a definitive conclusion, you MUST explicitly state that the provided local sources do not provide a sufficiently clear basis for a definitive answer. Do not guess or overgeneralize.
5. Distinguish between facts/reasoning directly present in the excerpts and broader legal conclusions. Do not invent broader legal conclusions.

WRITING THE ANSWER:
- Begin with a natural-language sentence that directly addresses the question.
- Write in Markdown. For a substantive question, organise the answer under short "### " headings chosen from: Short answer, Analysis, Applicable law, Relevant judgments, Conclusion. Use only the headings that genuinely help, and none for a simple question.
- Name statutes and cases in prose (e.g. "Section 138 of the Negotiable Instruments Act, 1881").
- After each claim that relies on an excerpt, add an inline citation marker [n], where n is the 1-based position of the supporting entry in your citations array, e.g. "...within thirty days [1]." A claim supported by several entries takes several markers, e.g. [1][2]. Every marker must have a matching citations entry.
- Never write doc_ids or tokens such as [SOURCE: xxx] in the answer text.

OUTPUT:
Submit your response with the submit_legal_answer tool, filling its parameters in this order:
1. "citations" — the evidence first: one entry per claim you will make, in the order you will cite them. \
Each entry has "doc_id" (copied from the cited excerpt's '--- doc_id: ... ---' header) and \
"evidence_quote" (the EXACT verbatim text, at least 5 words, from that excerpt that explicitly proves the claim).
2. "answer" — the Markdown answer, marking each claim with [n], where n is the 1-based position of its \
entry in citations. Never put a citation list inside the answer text.
"""

# The distillation answer instruction (the Claude teacher's dataset prompt, and what the LoRA student was
# trained with). The research app does not send it; the answer engines append it for every engine when
# ENGINE_ANSWER_INSTRUCTION=dataset so that all models see the identical prompt.
DATASET_ANSWER_INSTRUCTION = """Dataset answer requirements:
- Answer the question directly in the first sentence.
- Be concise: aim for 500 to 1,200 characters. Go longer only when the legal issue genuinely needs it. Never repeat a point, a caveat or a conclusion.
- Use only the excerpts above. Do not mention any Act, section, case or citation that does not appear in them.
- Mark every supported claim with [n]. When the answer compares or relies on several provisions or judgments, cite each one where it is used. Keep what the excerpts establish separate from anything they do not address.
- Stop once the question is answered: no closing recap, "Thus"/"Therefore" summary or "Conclusion" section that repeats earlier sentences.
- If the excerpts do not answer the question, reply in at most three sentences (about 500 characters): what they do establish [n] and, once, what is missing. Do not restate the gap, add a conclusion, or speculate.
- Use "### " headings only when the answer has several distinct parts."""

QUICK_ANSWER_INSTRUCTION = (
    "Answer mode: QUICK ANSWER. Reply in two to four sentences with no headings, "
    "still marking every supported claim with [n] citation markers."
)

_MARKER_PATTERN = re.compile(r"[ \t]*\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_DUPLICATE_MARKER_PATTERN = re.compile(r"(\[(\d+)\])(?:\[\2\])+")


def fix_leading_citation(text: str) -> str:
    text = text.strip()
    match = re.match(r'^(\[SOURCE:\s*[^\]]+\]|\[[A-Za-z0-9\-]+\])\s*(.*)', text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        citation = match.group(1).strip()
        remainder = match.group(2).strip()

        id_match = re.search(r'([A-Za-z0-9\-]+)', citation.replace("SOURCE:", "", 1))
        doc_id = id_match.group(1) if id_match else citation

        if doc_id not in remainder:
            sentence_end = re.search(r'([.?!])(?:\s|$)', remainder)
            if sentence_end:
                idx = sentence_end.start(1) + 1
                remainder = remainder[:idx] + " " + citation + remainder[idx:]
            else:
                remainder = remainder + " " + citation

        if remainder:
            remainder = remainder[0].upper() + remainder[1:]
        return remainder
    return text


def build_context(hits):
    instrumentation.log("8", "Context construction START")
    instrumentation.start("Context construction")
    blocks = []
    for h in hits:
        if not h["text"]:
            continue
        source_type = h.get("source_type")
        if source_type == "pdf":
            location = f"file: {h.get('file_name') or 'unknown file'} | page(s): {h.get('page_start')}-{h.get('page_end')}"
        elif source_type == "statute":
            location = f"enacted {h.get('date')}" if h.get("date") else "enactment date unknown"
        else:
            location = f"{h.get('court') or 'Unknown Court'}, {h.get('date') or 'Unknown Date'}"
        blocks.append(
            f"--- doc_id: {h['doc_id']} | {h['title']} ({location}) "
            f"| section: {h.get('section') or 'general'} ---\n{h['text']}"
        )
    result = "\n\n".join(blocks)
    dur = instrumentation.end("Context construction")
    instrumentation.log("8", f"Context construction END: {dur:.3f} sec")
    instrumentation.log("8", f"Context length: {len(result)} characters")
    return result


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[^\w\s]', '', text)
    return re.sub(r'\s+', ' ', text).lower().strip()


def resolve_citation_markers(text: str, index_to_number: dict) -> str:
    """Rewrite the model's [n] markers (positions in its citations array) to the
    numbers of the sources those citations deterministically mapped to. A marker
    whose citation matched no retrieved text resolves to nothing and is removed,
    so the answer can never point at evidence that wasn't verified."""
    def replace(match):
        numbers = []
        for part in match.group(1).split(","):
            number = index_to_number.get(int(part))
            if number and number not in numbers:
                numbers.append(number)
        return "".join(f"[{n}]" for n in numbers)

    resolved = _MARKER_PATTERN.sub(replace, text)
    return _DUPLICATE_MARKER_PATTERN.sub(r"\1", resolved)


def _hit_fields(h):
    return {
        "doc_id": h["doc_id"], "title": h["title"], "source_type": h.get("source_type"),
        "court": h.get("court") or None, "date": h.get("date") or None,
        "section": h.get("section") or None, "file_name": h.get("file_name") or None,
        "page_start": h.get("page_start") or None, "page_end": h.get("page_end") or None,
    }


def _retrieved_payload(h, cited_doc_ids):
    return {
        **_hit_fields(h), "source": h["source"], "score": h.get("score"),
        "rerank_score": h.get("rerank_score"), "excerpt": h["text"], "cited": h["doc_id"] in cited_doc_ids,
        "retrieval_ranks": h.get("retrieval_ranks"), "required_reason": h.get("required_reason"),
        "chunk_id": h.get("chunk_id"), "chunk_ids": h.get("chunk_ids"), "context_span": h.get("context_span"),
    }


def _empty_result(message, accuracy_note, mode, error=None, hits=None):
    result = {
        "raw_answer": message,
        "clean_answer": message,
        "answer_markdown": message,
        "verified": [],
        "unverified": [],
        "citations": [],
        "unmatched_citations": 0,
        "accuracy_note": accuracy_note,
        "mode": mode,
        "retrieved_documents": [_retrieved_payload(h, set()) for h in (hits or [])],
    }
    if error:
        result["error"] = error
    return result


def _stage_emitter(on_stage):
    def emit(stage, status, detail=None):
        if on_stage is None:
            return
        try:
            on_stage(stage, status, detail or {})
        except Exception:
            logger.exception("on_stage callback raised; continuing")
    return emit


def evidence_fingerprint(question: str, top_k: int, hits) -> str:
    """Identifies one frozen evidence selection: the question, top_k and every selected passage."""
    digest = hashlib.sha256(f"{' '.join(question.lower().split())}|{top_k}".encode("utf-8"))
    for hit in hits:
        digest.update(hit["doc_id"].encode("utf-8"))
        digest.update(hashlib.sha1((hit.get("text") or "").encode("utf-8")).digest())
    return "ev-" + digest.hexdigest()[:16]


def retrieve_evidence(question: str, top_k: int = 5, on_stage=None):
    """Retrieval, reranking and evidence selection only. The returned bundle is everything generation
    needs, so several answer models can be given the identical evidence (see engines.py)."""
    emit = _stage_emitter(on_stage)
    started = time.perf_counter()
    try:
        hits, retrieval_plan = hybrid_search_with_plan(question, top_k=top_k, on_stage=emit)
    except Exception:
        logger.exception("Retrieval failed for question=%r", question)
        emit("search", "failed")
        return {"question": question, "top_k": top_k, "hits": [], "retrieval_plan": None, "error": "retrieval",
                "retrieval_s": time.perf_counter() - started, "created_at": time.time(), "evidence_id": None}
    return {
        "question": question, "top_k": top_k, "hits": hits, "retrieval_plan": retrieval_plan, "error": None,
        "retrieval_s": time.perf_counter() - started, "created_at": time.time(),
        "evidence_id": evidence_fingerprint(question, top_k, hits),
    }


def answer_question(question: str, top_k: int = 5, on_stage=None, mode: str = "research", answer_instruction: str = None):
    """`on_stage(stage, status, detail)` is called as real pipeline steps start and
    finish (semantic, keyword, ranking, drafting, verification); `mode="quick"` asks
    for a short answer from the same retrieval and verification pipeline.
    `answer_instruction`, when given, is appended to the question like the quick-answer instruction
    (used by the distillation teacher; the app never passes it)."""
    evidence = retrieve_evidence(question, top_k=top_k, on_stage=on_stage)
    return answer_from_evidence(question, evidence, mode=mode, answer_instruction=answer_instruction, on_stage=on_stage)


def answer_from_evidence(question: str, evidence, mode: str = "research", answer_instruction: str = None, on_stage=None,
                         generate_fn=None, model_label: str = None, unavailable_message: str = None):
    """Prompt → generation → citation mapping → citation verification on an already-selected evidence bundle.
    `generate_fn(system_prompt, user_content)` replaces the configured LLM provider (answer engines use it
    to pick a model per request); every model goes through the same mapping and verification below."""
    emit = _stage_emitter(on_stage)
    started = time.perf_counter()
    if evidence.get("error"):
        return _empty_result(
            "The search service is currently unavailable. Please try again shortly.",
            "Retrieval failed", mode, error="retrieval",
        )
    hits, retrieval_plan = evidence["hits"], evidence["retrieval_plan"]
    retrieval_s = 0.0 if evidence.get("reused") else evidence.get("retrieval_s", 0.0)
    started -= retrieval_s

    context = build_context(hits)

    if not context.strip():
        return _empty_result(
            "No relevant legal documents were found in the database for this query.",
            "No citations were made", mode,
        )

    instrumentation.log("9", "Prompt construction START")
    instrumentation.start("Prompt construction")
    user_content = f"Excerpts:\n{context}\n\nQuestion: {question}"
    if mode == "quick":
        user_content += f"\n\n{QUICK_ANSWER_INSTRUCTION}"
    if answer_instruction:
        user_content += f"\n\n{answer_instruction}"
    dur_prompt = instrumentation.end("Prompt construction")
    instrumentation.log("9", f"Prompt construction END: {dur_prompt:.3f} sec")

    model_label = model_label or settings.llm_model
    emit("drafting", "started", {"model": model_label, "sources": sum(1 for h in hits if h["text"])})
    call_num = instrumentation.increment_api_call()
    instrumentation.log("LLM", f"Generation call #{call_num} START")
    instrumentation.start("Actual API call")
    generation_started = time.perf_counter()
    try:
        generate = generate_fn or get_llm_provider().generate_structured_answer
        llm_result = generate(SYSTEM_PROMPT, user_content)
    except Exception:
        logger.exception("LLM generation failed for question=%r (%s)", question, model_label)
        emit("drafting", "failed")
        failed = _empty_result(
            unavailable_message or "The answer generation service is currently unavailable. Please try again shortly.",
            "Answer generation failed", mode, error="generation", hits=hits,
        )
        failed["timings"] = {"retrieval_s": round(retrieval_s, 3), "generation_s": round(time.perf_counter() - generation_started, 3),
                             "total_s": round(time.perf_counter() - started, 3)}
        failed["user_content"] = user_content
        return failed
    generation_s = time.perf_counter() - generation_started
    dur_call = instrumentation.end("Actual API call")
    instrumentation.log("LLM", f"Generation call END: {dur_call:.3f} sec")
    emit("drafting", "done")

    raw_answer = llm_result.get("answer", "") or "No answer was generated."
    evidence_list = llm_result.get("citations", [])
    raw_answer = fix_leading_citation(raw_answer)

    emit("verification", "started", {"claims": len(evidence_list)})
    instrumentation.start("Final processing")
    instrumentation.start("Evidence reference extraction")

    # The LLM's self-reported doc_id is ignored; the authoritative doc_id is the one on the chunk whose text contains the quote.
    hit_list = [{"norm_text": normalize_text(h["text"]), "hit": h} for h in hits if h["text"]]

    sources = OrderedDict()
    index_to_number = {}
    unmatched = 0
    for index, cit in enumerate(evidence_list, 1):
        quote = cit.get("evidence_quote", "")
        norm_q = normalize_text(quote)
        match = next((h["hit"] for h in hit_list if norm_q and norm_q in h["norm_text"]), None)
        if match is None:
            unmatched += 1
            continue
        doc_id = match["doc_id"]
        if doc_id not in sources:
            sources[doc_id] = {
                **_hit_fields(match), "number": len(sources) + 1,
                "excerpt": match["text"], "passages": [], "quotes": [],
            }
        source = sources[doc_id]
        if match["text"] not in source["passages"]:
            source["passages"].append(match["text"])
        if quote not in source["quotes"]:
            source["quotes"].append(quote)
        index_to_number[index] = source["number"]
    dur_ev = instrumentation.end("Evidence reference extraction")
    instrumentation.log("15", f"Evidence extraction END: {dur_ev:.3f} sec")

    instrumentation.start("Python citation mapping")
    answer_markdown = resolve_citation_markers(raw_answer, index_to_number).strip()
    source_tokens = " ".join(f"[SOURCE: {doc_id}]" for doc_id in sources)
    raw_with_tokens = f"{answer_markdown} {source_tokens}".strip()
    dur_map = instrumentation.end("Python citation mapping")
    instrumentation.log("15", f"Python citation mapping END: {dur_map:.3f} sec")
    instrumentation.end("Final processing")

    verification = verify_citations(raw_with_tokens, set(sources))
    verified_ids = {v["doc_id"] for v in verification["verified"]}
    for source in sources.values():
        source["verified"] = source["doc_id"] in verified_ids
    emit("verification", "done", {
        "verified": len(verified_ids), "unverified": len(verification["unverified"]), "unmatched": unmatched,
    })

    timings = {
        "retrieval_s": round(retrieval_s, 3),
        "generation_s": round(generation_s, 3),
        "total_s": round(time.perf_counter() - started, 3),
        "prompt_chars": len(SYSTEM_PROMPT) + len(user_content),
    }
    logger.info(
        "answer timings (%s): retrieval %.2fs, generation %.2fs, total %.2fs, prompt %d chars",
        model_label, timings["retrieval_s"], timings["generation_s"], timings["total_s"], timings["prompt_chars"],
    )

    return {
        "timings": timings,
        "raw_answer": raw_with_tokens,
        "answer_markdown": answer_markdown,
        "citations": list(sources.values()),
        "unmatched_citations": unmatched,
        "retrieved_documents": [_retrieved_payload(h, set(sources)) for h in hits],
        "extracted_evidence": evidence_list,
        "validated_ids": list(sources),
        "mode": mode,
        "retrieval_plan": retrieval_plan,
        "user_content": user_content,
        "generation": llm_result.get("generation"),
        **verification,
    }


if __name__ == "__main__":
    q = "If a demand notice is returned undelivered, is the complaint still valid under Section 138?"
    result = answer_question(q)
    print("QUESTION:", q)
    print("\nANSWER:\n", result["answer_markdown"])
    print("\n", result["accuracy_note"])
    if result["unverified"]:
        print("UNVERIFIED:", result["unverified"])
