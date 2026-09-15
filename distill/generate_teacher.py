"""
Stage 2 — teacher answers from the real IndianLawGPT pipeline, with quality gates.

Each question goes through rag_chain.answer_question() exactly as the app runs it — planned hybrid
retrieval (explicit sources reserved, RRF discovery), Claude given only the selected evidence, deterministic
citation mapping and citation verification — plus one dataset-only instruction appended to the question
(TEACHER_INSTRUCTION: direct, concise, evidence-first). The app itself never sends that instruction.

Every example is then graded:
  * deterministic checks — pipeline errors, unverified or unretrieved citations, markers without sources,
    internal/tool markup, retrieval of every required authority, explicit references missing from context;
  * an independent grader call — is every claim supported by the excerpts, does it answer the question,
    what answer type is it, and is any statement of insufficiency justified by the excerpts;
and receives quality_status VERIFIED, NEEDS_REVIEW or REJECTED. An "insufficient evidence" answer to an
answerable question whose required source was not retrieved is classified
FALSE_INSUFFICIENT_RETRIEVAL_FAILURE and can never be VERIFIED.

Resumable and parallel: one record per question is appended to teacher_records.jsonl as soon as it
finishes; a restarted run skips recorded questions. --retry-errors re-runs pipeline failures.

Usage (from the repository root):
    .venv/bin/python distill/generate_teacher.py --run pilot_v2 --workers 4
"""
import argparse
import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import append_jsonl, call_claude_tool, get_logger, latest_by_id, log_failure, now_iso, read_jsonl, run_dir, settings
from db import get_documents_brief
from rag_chain import DATASET_ANSWER_INSTRUCTION, SYSTEM_PROMPT, answer_question

logger = get_logger("distill.teacher")

TOP_K = 5  # same as the app's research mode
PIPELINE_ATTEMPTS = 3
LONG_ANSWER_CHARS = 1200
MAX_ANSWER_CHARS = 3000

# Canonical text lives in rag_chain so the answer engines send the identical instruction (unchanged wording).
TEACHER_INSTRUCTION = DATASET_ANSWER_INSTRUCTION

PROMPT_VERSION = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]
INSTRUCTION_VERSION = hashlib.sha256(TEACHER_INSTRUCTION.encode("utf-8")).hexdigest()[:12]
MARKER = re.compile(r"\[(\d+)\]")
STATES_INSUFFICIENCY = re.compile(
    r"do(?:es)? not (?:contain|provide|specify|address|state|mention|establish|set out|include|cover|offer|prescribe)"
    r"|(?:in|not\s+)sufficient"
    r"|no (?:clear|sufficient|specific|direct|explicit) (?:basis|answer|guidance|provision|information|rule)"
    r"|cannot be (?:determined|answered|conclusively)"
    r"|not (?:addressed|covered|stated|specified|discussed|mentioned) in"
    r"|silent on",
    re.IGNORECASE,
)
# Tool/XML markup, source tokens or raw database ids must never reach a training answer.
INTERNAL_LEAK = re.compile(
    r"</?[A-Za-z_][\w:.-]*(?:\s[^<>]*)?/?>|\[SOURCE:|\bdoc_id\b|\bSTATUTE-[a-z0-9-]+-s[0-9a-z]+\b|\bNI138-[0-9a-z-]+\b|submit_legal_answer"
)

JUDGE_TOOL = {
    "name": "grade_answer",
    "description": "Grade a legal answer strictly against the excerpts it was given.",
    "input_schema": {
        "type": "object",
        "properties": {
            "supported": {"type": "boolean", "description": "Every legal claim in the answer is supported by the excerpts."},
            "unsupported_claims": {"type": "array", "items": {"type": "string"}},
            "invented_authority": {"type": "boolean", "description": "The answer names an Act, section, case or citation that is not in the excerpts."},
            "answers_question": {"type": "boolean"},
            "answer_type": {"type": "string", "enum": ["cited_answer", "partial_answer", "insufficient_evidence"]},
            "insufficiency_justified": {
                "type": "boolean",
                "description": "Only for partial_answer or insufficient_evidence: the information the answer says is missing is truly absent from the excerpts. True for cited_answer.",
            },
            "concise": {"type": "boolean", "description": "No padding, repeated points or restated caveats; the length fits the question."},
            "judgment_excerpts_supporting_principle": {
                "type": "array", "items": {"type": "integer"},
                "description": "Numbers of the judgment excerpts that themselves state the legal position the question asks about. Empty if none do or the question does not ask about a judicial position.",
            },
            "notes": {"type": "string"},
        },
        "required": ["supported", "unsupported_claims", "invented_authority", "answers_question", "answer_type",
                     "insufficiency_justified", "concise", "judgment_excerpts_supporting_principle", "notes"],
    },
}

JUDGE_SYSTEM = """You grade answers produced by an Indian legal research assistant. Judge ONLY against the excerpts shown; do not use outside legal knowledge to add or excuse claims.
- supported: false if any legal claim (rule, figure, time limit, condition, holding) is not stated in the excerpts.
- invented_authority: true if the answer names any Act, section, case, citation or court that does not appear in the excerpts.
- answers_question: true if the answer responds to what was actually asked. A clear, justified statement that the excerpts do not contain the answer counts as responding.
- answer_type: cited_answer (answers the question from the excerpts), partial_answer (answers part and says the rest is not in the excerpts), insufficient_evidence (says the excerpts do not answer it).
- insufficiency_justified: for partial_answer or insufficient_evidence, true only if the excerpts really lack what the answer says is missing; if an excerpt contains it, false.
- concise: false if the answer pads, repeats a point, or restates the same caveat or conclusion.
- judgment_excerpts_supporting_principle: list the numbers of judgment excerpts whose own text states the legal position the question asks about (not merely mentioning the topic)."""

_write_lock = threading.Lock()


def source_details(doc_ids):
    details = {}
    for row in get_documents_brief(doc_ids):
        meta = json.loads(row.get("metadata_json") or "{}")
        details[row["doc_id"]] = {
            "title": row["title"], "source_type": row["source_type"], "court": row["court"] or None,
            "date": row["date"] or None, "act_id": meta.get("act_id"), "act_title": meta.get("act_title"),
            "section_number": meta.get("section_number"), "section_heading": meta.get("section_heading"),
            "source_url": meta.get("source_url"),
        }
    return details


def seed_authorities(question):
    """Authorities the question needs. Legacy questions (no recorded authorities) treat every seed doc_id
    as its own exact authority; insufficient_evidence questions need none."""
    authorities = question["seed"].get("authorities")
    if authorities is not None:
        return authorities
    return [{"doc_ids": [doc_id], "equivalence": "exact", "kind": "unknown"} for doc_id in question["seed"]["doc_ids"]]


def seed_coverage(question, retrieved_ids, cited_ids):
    """An authority is covered when any of its accepted documents (the exact seed, or for principle-based
    case law any judgment stating the same principle) was retrieved / cited."""
    authorities = seed_authorities(question)
    rows = []
    for authority in authorities:
        accepted = set(authority["doc_ids"])
        retrieved = sorted(accepted & set(retrieved_ids))
        rows.append({
            "source_doc_id": authority.get("source_doc_id") or authority["doc_ids"][0],
            "kind": authority.get("kind"), "equivalence": authority.get("equivalence"), "accepted_doc_count": len(accepted),
            "retrieved_doc_ids": retrieved, "cited_doc_ids": sorted(accepted & set(cited_ids)),
            "satisfied_by": None if not retrieved else "exact" if authority.get("equivalence", "exact") == "exact" else "phrase_equivalent",
        })
    return {"required_sources": rows, "seed_cited": any(r["cited_doc_ids"] for r in rows), **coverage_summary(rows)}


def coverage_summary(rows):
    satisfied = [bool(r["satisfied_by"]) for r in rows]
    return {
        "seed_retrieved": any(satisfied) if rows else True,
        "seed_all_retrieved": all(satisfied),
        "seed_authorities_retrieved": f"{sum(satisfied)}/{len(rows)}",
    }


def confirm_principle_equivalents(checks, retrieved, judge):
    """A principle-based case-law authority is also satisfied by a retrieved judgment that the grader found
    states the same legal position in its own words (the verbatim-phrase set is only a lower bound).
    Specific-judgment authorities are never satisfied this way."""
    numbers = judge.get("judgment_excerpts_supporting_principle") or []
    confirmed = sorted({
        retrieved[n - 1]["doc_id"] for n in numbers
        if isinstance(n, int) and 1 <= n <= len(retrieved) and retrieved[n - 1].get("source_type") == "case_law"
    })
    for row in checks["required_sources"]:
        if row["equivalence"] == "principle" and not row["satisfied_by"] and confirmed:
            row["grader_confirmed_equivalents"] = confirmed
            row["satisfied_by"] = "grader_confirmed_equivalent"
    checks.update(coverage_summary(checks["required_sources"]))
    return checks


def quote_supported_ids(citations, retrieved):
    """Retrieved documents whose text contains a verified evidence quote. Citation mapping credits a quote to
    the first excerpt containing it, so when an old and a new provision are worded identically only one is
    listed as cited although the quote is evidence from both."""
    def norm(text):
        return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))
    quotes = [norm(q) for c in citations if c["verified"] for q in c.get("evidence_quotes") or []]
    quotes = [q for q in quotes if len(q.split()) >= 5]
    return {d["doc_id"] for d in retrieved if any(q in norm(d.get("excerpt") or d.get("text")) for q in quotes)}


def quality_checks(question, result, answer, citations, retrieved):
    markers = sorted({int(m) for m in MARKER.findall(answer)})
    numbers = {c["number"] for c in citations}
    retrieved_ids = {d["doc_id"] for d in retrieved}
    cited_ids = {c["doc_id"] for c in citations} | quote_supported_ids(citations, retrieved)
    plan = result.get("retrieval_plan") or {}
    return {
        "pipeline_error": result.get("error"),
        "retrieved_documents": len(retrieved_ids),
        "llm_quotes": len(result.get("extracted_evidence") or []),
        "unmatched_quotes": result.get("unmatched_citations", 0),
        "verified_sources": sum(1 for c in citations if c["verified"]),
        "unverified_sources": len(result.get("unverified") or []),
        "cited_not_retrieved": sorted(cited_ids - retrieved_ids),
        "inline_markers": markers,
        "sources_without_marker": sorted(numbers - set(markers)),
        "markers_without_source": sorted(set(markers) - numbers),
        "states_insufficiency": bool(STATES_INSUFFICIENCY.search(answer)),
        **seed_coverage(question, retrieved_ids, cited_ids),
        "explicit_requirements_missing": [
            m for m in plan.get("missing_requirements") or [] if m.get("reason") in ("explicit_reference", "mapped_counterpart")
        ],
        "answer_chars": len(answer),
        "internal_markup_leak": bool(INTERNAL_LEAK.search(answer)),
    }


def run_judge(question, result, answer):
    excerpts = "\n\n".join(
        f"--- Excerpt {i} ({'judgment' if d.get('source_type') == 'case_law' else 'statute'}): {d.get('title')} ---\n{d.get('excerpt') or ''}"
        for i, d in enumerate(result.get("retrieved_documents") or [], 1)
    )
    prompt = f"Excerpts:\n{excerpts}\n\nQuestion: {question['question']}\n\nAnswer to grade:\n{answer}"
    try:
        verdict = call_claude_tool(JUDGE_TOOL, JUDGE_SYSTEM, prompt, max_tokens=900)
        return {**verdict, "grader_model": settings.anthropic_model, "error": None}
    except Exception as error:
        return {"error": str(error), "grader_model": settings.anthropic_model}


def grade(question, checks, judge):
    """Returns (quality_status, reasons, answer_type, insufficiency_classification)."""
    rejected = []
    if checks["pipeline_error"]:
        rejected.append(f"pipeline_error:{checks['pipeline_error']}")
    if checks["retrieved_documents"] == 0:
        rejected.append("no_retrieved_evidence")
    if checks["answer_chars"] < 40:
        rejected.append("empty_or_trivial_answer")
    if checks["unverified_sources"]:
        rejected.append("unverified_citation")
    if checks["cited_not_retrieved"]:
        rejected.append("citation_not_in_retrieved_evidence")
    if checks["markers_without_source"]:
        rejected.append("marker_without_source")
    if checks["internal_markup_leak"]:
        rejected.append("internal_markup_leak")
    insufficient_answer = checks["verified_sources"] == 0 and checks["states_insufficiency"]
    if checks["verified_sources"] == 0 and not insufficient_answer:
        rejected.append("no_verified_citations")
    if judge.get("invented_authority"):
        rejected.append("grader_found_invented_authority")
    if rejected:
        return "REJECTED", rejected, None, None

    answer_type = "insufficient_evidence" if insufficient_answer else "partial_answer" if checks["states_insufficiency"] else "cited_answer"
    review = []
    if judge.get("error"):
        review.append("grader_unavailable")
    else:
        if not judge.get("supported"):
            review.append("grader_unsupported_claims")
        if not judge.get("answers_question"):
            review.append("grader_does_not_answer_question")
        judged = judge.get("answer_type")
        if checks["verified_sources"] == 0 and judged == "cited_answer":
            review.append("answer_type_disagreement")  # presented as an answer, but nothing in it is verified
        elif answer_type == "cited_answer" and judged in ("partial_answer", "insufficient_evidence"):
            review.append("answer_type_disagreement")  # reads as an answer, but the grader finds gaps it does not state
        elif judged:
            # The insufficiency phrase detector also fires on legal wording ("is not sufficient to rebut"), so
            # for an answer with verified citations the grader's reading of its type is used.
            answer_type = judged
        if answer_type != "cited_answer" and not judge.get("insufficiency_justified"):
            review.append("insufficiency_not_justified_by_excerpts")
        if judge.get("concise") is False:
            review.append("answer_not_concise")

    classification = None
    if question["expected"] == "insufficient":
        check = question.get("insufficiency_check") or {}
        if check.get("classification") != "TRUE_INSUFFICIENT":
            review.append("insufficiency_label_unvalidated")
        if answer_type == "cited_answer":
            review.append("expected_insufficient_but_answered")
        classification = "TRUE_INSUFFICIENT" if check.get("classification") == "TRUE_INSUFFICIENT" else "UNVALIDATED"
    else:
        if not question.get("validation", {}).get("accepted"):
            review.append("question_not_validated")
        if not checks["seed_all_retrieved"]:
            review.append("required_source_not_retrieved")
        if checks["explicit_requirements_missing"]:
            review.append("explicit_reference_not_in_context")
        if answer_type != "cited_answer":
            if not checks["seed_all_retrieved"]:
                classification = "FALSE_INSUFFICIENT_RETRIEVAL_FAILURE"
                review.append("false_insufficient_retrieval_failure")
            else:
                classification = "PARTIAL_WITH_REQUIRED_SOURCES"
        if answer_type == "insufficient_evidence":
            review.append("answerable_question_answered_as_insufficient")
        required = checks.get("required_sources") or []
        if answer_type == "cited_answer" and len(required) > 1 and any(
            r.get("kind") == "statute" and r["retrieved_doc_ids"] and not r["cited_doc_ids"] for r in required
        ):
            review.append("required_source_not_cited")
    if checks["verified_sources"]:
        if checks["unmatched_quotes"]:
            review.append("some_quotes_unmatched")
        if not checks["inline_markers"]:
            review.append("no_inline_citation_markers")
        elif checks["sources_without_marker"]:
            review.append("cited_source_not_referenced_inline")
    if checks["answer_chars"] > MAX_ANSWER_CHARS:
        review.append("answer_too_long")
    return ("NEEDS_REVIEW" if review else "VERIFIED"), review, answer_type, classification


def build_record(question, result, attempts, elapsed):
    retrieved = result.get("retrieved_documents") or []
    answer = result.get("answer_markdown") or ""
    timings = result.get("timings") or {}
    doc_ids = list(dict.fromkeys([d["doc_id"] for d in retrieved] + [c["doc_id"] for c in result.get("citations") or []]))
    details = source_details(doc_ids)

    retrieved_context = [
        {
            "rank": rank, "doc_id": d["doc_id"], "retrieval": d.get("source"), "retrieval_ranks": d.get("retrieval_ranks"),
            "required_reason": d.get("required_reason"), "score": d.get("score"), "rerank_score": d.get("rerank_score"),
            "chunk_label": d.get("section"), "chunk_id": d.get("chunk_id"), "chunk_ids": d.get("chunk_ids"),
            "context_span": d.get("context_span"), "cited": d.get("cited"),
            **details.get(d["doc_id"], {"title": d.get("title"), "source_type": d.get("source_type")}),
            "text": d.get("excerpt") or "",
        }
        for rank, d in enumerate(retrieved, 1)
    ]
    citations = [
        {
            "number": c["number"], "doc_id": c["doc_id"], "verified": c["verified"],
            **details.get(c["doc_id"], {"title": c.get("title"), "source_type": c.get("source_type")}),
            "evidence_quotes": c.get("quotes") or [], "passages": c.get("passages") or [],
        }
        for c in result.get("citations") or []
    ]
    checks = quality_checks(question, result, answer, citations, retrieved)
    judge = run_judge(question, result, answer) if not checks["pipeline_error"] and answer else {"error": "not_run"}
    if not judge.get("error"):
        confirm_principle_equivalents(checks, retrieved, judge)
    status, reasons, answer_type, classification = grade(question, checks, judge)

    return {
        "id": question["id"],
        "question": question["question"],
        "category": question["category"],
        "case_law_type": question.get("case_law_type"),
        "expected": question["expected"],
        "answer_type": answer_type,
        "quality_status": status,
        "status": status.lower(),
        "status_reasons": reasons,
        "insufficiency_classification": classification,
        "refusal_training_eligible": status == "VERIFIED" and classification == "TRUE_INSUFFICIENT" and answer_type == "insufficient_evidence",
        "intended_source_ids": question["seed"]["doc_ids"],
        "required_sources": checks["required_sources"],
        "retrieved_source_ids": [d["doc_id"] for d in retrieved],
        "retrieved_all_required_sources": checks["seed_all_retrieved"],
        "missing_required_sources": [r["source_doc_id"] for r in checks["required_sources"] if not r["satisfied_by"]],
        "retrieval_trace": {k: v for k, v in (result.get("retrieval_plan") or {}).items() if k != "fused_top"},
        "retrieved_context": retrieved_context,
        "teacher_prompt": {
            "system_prompt_version": PROMPT_VERSION, "answer_instruction_version": INSTRUCTION_VERSION,
            "system_prompt": SYSTEM_PROMPT, "user_content": result.get("user_content"),
        },
        "teacher_answer": answer,
        "citations": citations,
        "verified_citations": [c["doc_id"] for c in citations if c["verified"]],
        "source_ids": [c["doc_id"] for c in citations],
        # Output in the pipeline's structured shape; [n] in the answer refers to target.citations[n-1].
        "target": {
            "citations": [{"doc_id": c["doc_id"], "evidence_quote": c["evidence_quotes"][0]} for c in citations if c["evidence_quotes"]],
            "answer": answer,
        },
        "checks": checks,
        "grader": judge,
        "question_record": {k: question.get(k) for k in ("expected", "validation", "insufficiency_check")},
        "seed": question["seed"],
        "question_validation": question.get("validation") or question.get("insufficiency_check"),
        "teacher": {
            "model": settings.anthropic_model, "pipeline_attempts": attempts, "timings": timings,
            "wall_s": round(elapsed, 3), "accuracy_note": result.get("accuracy_note"),
            "raw_llm_citations": result.get("extracted_evidence") or [],
        },
        "created_at": now_iso(),
    }


def answer_one(run, question):
    started = time.perf_counter()
    result, attempt = None, 0
    for attempt in range(1, PIPELINE_ATTEMPTS + 1):
        try:
            result = answer_question(question["question"], top_k=TOP_K, mode="research", answer_instruction=TEACHER_INSTRUCTION)
        except Exception as error:
            log_failure(run, "teacher", "pipeline_exception", id=question["id"], attempt=attempt, error=str(error))
            result = {"error": "exception"}
        if not result.get("error") and (result.get("answer_markdown") or "").strip() == "No answer was generated.":
            # An empty structured response from the model is a transient generation failure, not an answer.
            result = {**result, "error": "empty_model_answer"}
        if not result.get("error"):
            break
        log_failure(run, "teacher", f"pipeline_error:{result['error']}", id=question["id"], attempt=attempt)
        if attempt < PIPELINE_ATTEMPTS:
            time.sleep(5 * attempt)
    return build_record(question, result, attempt, time.perf_counter() - started)


def main():
    parser = argparse.ArgumentParser(description="Generate graded teacher answers with the IndianLawGPT pipeline.")
    parser.add_argument("--run", required=True)
    parser.add_argument("--limit", type=int, default=None, help="Process at most N pending questions.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retry-errors", action="store_true", help="Re-run questions that previously hit a pipeline error.")
    args = parser.parse_args()

    run = run_dir(args.run)
    questions = read_jsonl(run / "questions.jsonl")
    if not questions:
        raise SystemExit(f"No questions in {run / 'questions.jsonl'} - run build_questions.py first.")
    records_path = run / "teacher_records.jsonl"
    done = latest_by_id(read_jsonl(records_path))

    def pending(question):
        record = done.get(question["id"])
        if record is None:
            return True
        return args.retry_errors and any(reason.startswith("pipeline_error") for reason in record["status_reasons"])

    todo = [q for q in questions if pending(q)]
    if args.limit:
        todo = todo[: args.limit]
    logger.info("Run '%s': %d questions, %d already recorded, %d to process", args.run, len(questions), len(done), len(todo))

    finished = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(answer_one, run, question): question for question in todo}
        for future in as_completed(futures):
            question = futures[future]
            try:
                record = future.result()
            except Exception as error:
                log_failure(run, "teacher", "record_exception", id=question["id"], error=str(error))
                continue
            with _write_lock:
                append_jsonl(records_path, record)
                finished += 1
            if record["quality_status"] == "REJECTED":
                log_failure(run, "teacher", "rejected", id=question["id"], category=question["category"], reasons=record["status_reasons"])
            logger.info(
                "[%d/%d] %-12s %-22s chars=%d sources=%d %s",
                finished, len(todo), record["quality_status"], question["category"], record["checks"]["answer_chars"],
                record["checks"]["verified_sources"], ",".join(record["status_reasons"]) or "-",
            )


if __name__ == "__main__":
    main()
