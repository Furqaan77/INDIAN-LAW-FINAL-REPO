"""
Offline tests of the teacher quality gates in distill/generate_teacher.py (no Claude calls).

Usage (from the repository root):
    .venv/bin/python distill/diagnostics/test_teacher_grading.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "distill"))

from generate_teacher import INTERNAL_LEAK, confirm_principle_equivalents, grade, quote_supported_ids  # noqa: E402

failures = []


def check(name, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {name}{('  — ' + str(detail)) if detail else ''}")
    if not condition:
        failures.append(name)


CLEAN_CHECKS = {
    "pipeline_error": None, "retrieved_documents": 5, "answer_chars": 800, "unverified_sources": 0,
    "cited_not_retrieved": [], "markers_without_source": [], "internal_markup_leak": False, "verified_sources": 2,
    "states_insufficiency": False, "seed_all_retrieved": True, "explicit_requirements_missing": [], "unmatched_quotes": 0,
    "inline_markers": [1, 2], "sources_without_marker": [],
}
GOOD_JUDGE = {"supported": True, "unsupported_claims": [], "invented_authority": False, "answers_question": True,
              "answer_type": "cited_answer", "insufficiency_justified": True, "concise": True,
              "judgment_excerpts_supporting_principle": [], "error": None}
ANSWERABLE = {"expected": "answerable", "validation": {"accepted": True}}
INSUFFICIENT = {"expected": "insufficient", "insufficiency_check": {"classification": "TRUE_INSUFFICIENT"}}


def main():
    status, reasons, answer_type, _ = grade(ANSWERABLE, CLEAN_CHECKS, GOOD_JUDGE)
    check("clean cited answer -> VERIFIED", status == "VERIFIED" and answer_type == "cited_answer", reasons)

    status, reasons, _, _ = grade(ANSWERABLE, {**CLEAN_CHECKS, "unverified_sources": 1}, GOOD_JUDGE)
    check("unverified citation -> REJECTED", status == "REJECTED" and "unverified_citation" in reasons, reasons)
    status, reasons, _, _ = grade(ANSWERABLE, {**CLEAN_CHECKS, "internal_markup_leak": True}, GOOD_JUDGE)
    check("internal markup in answer -> REJECTED", status == "REJECTED" and "internal_markup_leak" in reasons, reasons)
    status, reasons, _, _ = grade(ANSWERABLE, CLEAN_CHECKS, {**GOOD_JUDGE, "invented_authority": True})
    check("invented authority -> REJECTED", status == "REJECTED" and "grader_found_invented_authority" in reasons, reasons)
    status, reasons, _, _ = grade(ANSWERABLE, {**CLEAN_CHECKS, "cited_not_retrieved": ["STATUTE-x-s1"]}, GOOD_JUDGE)
    check("citation outside retrieved evidence -> REJECTED", status == "REJECTED", reasons)

    insufficient_answer = {**CLEAN_CHECKS, "verified_sources": 0, "states_insufficiency": True, "inline_markers": []}
    status, reasons, answer_type, classification = grade(
        ANSWERABLE, {**insufficient_answer, "seed_all_retrieved": False},
        {**GOOD_JUDGE, "answer_type": "insufficient_evidence", "insufficiency_justified": True})
    check("'insufficient' answer after a retrieval miss -> FALSE_INSUFFICIENT_RETRIEVAL_FAILURE, never VERIFIED",
          status == "NEEDS_REVIEW" and classification == "FALSE_INSUFFICIENT_RETRIEVAL_FAILURE" and "false_insufficient_retrieval_failure" in reasons, reasons)

    status, reasons, answer_type, classification = grade(
        ANSWERABLE, {**CLEAN_CHECKS, "states_insufficiency": True},
        {**GOOD_JUDGE, "answer_type": "partial_answer", "insufficiency_justified": True})
    check("partial answer with every required source retrieved and a justified gap -> VERIFIED partial",
          status == "VERIFIED" and answer_type == "partial_answer" and classification == "PARTIAL_WITH_REQUIRED_SOURCES", reasons)
    status, reasons, _, _ = grade(
        ANSWERABLE, {**CLEAN_CHECKS, "states_insufficiency": True},
        {**GOOD_JUDGE, "answer_type": "partial_answer", "insufficiency_justified": False})
    check("claimed gap that the excerpts actually cover -> NEEDS_REVIEW", "insufficiency_not_justified_by_excerpts" in reasons, reasons)

    status, reasons, answer_type, classification = grade(
        INSUFFICIENT, insufficient_answer, {**GOOD_JUDGE, "answer_type": "insufficient_evidence", "insufficiency_justified": True})
    check("validated insufficient question with justified refusal -> VERIFIED TRUE_INSUFFICIENT",
          status == "VERIFIED" and answer_type == "insufficient_evidence" and classification == "TRUE_INSUFFICIENT", reasons)
    status, reasons, _, classification = grade(
        {"expected": "insufficient"}, insufficient_answer, {**GOOD_JUDGE, "answer_type": "insufficient_evidence"})
    check("insufficient label never validated -> NEEDS_REVIEW", status == "NEEDS_REVIEW" and "insufficiency_label_unvalidated" in reasons, reasons)
    status, reasons, _, _ = grade(INSUFFICIENT, CLEAN_CHECKS, GOOD_JUDGE)
    check("insufficient question answered as if answerable -> NEEDS_REVIEW", "expected_insufficient_but_answered" in reasons, reasons)

    status, reasons, _, _ = grade(ANSWERABLE, CLEAN_CHECKS, {**GOOD_JUDGE, "supported": False})
    check("claims not supported by excerpts -> NEEDS_REVIEW", status == "NEEDS_REVIEW" and "grader_unsupported_claims" in reasons, reasons)
    status, reasons, _, _ = grade(ANSWERABLE, {**CLEAN_CHECKS, "explicit_requirements_missing": [{"doc_id": "STATUTE-ipc-s1"}]}, GOOD_JUDGE)
    check("explicitly named section missing from context -> NEEDS_REVIEW", "explicit_reference_not_in_context" in reasons, reasons)
    status, reasons, _, _ = grade({"expected": "answerable"}, CLEAN_CHECKS, GOOD_JUDGE)
    check("question without validation -> NEEDS_REVIEW", "question_not_validated" in reasons, reasons)
    status, reasons, _, _ = grade(ANSWERABLE, CLEAN_CHECKS, {"error": "timeout"})
    check("grader unavailable -> NEEDS_REVIEW", status == "NEEDS_REVIEW" and "grader_unavailable" in reasons, reasons)

    status, reasons, answer_type, classification = grade(
        INSUFFICIENT, {**CLEAN_CHECKS, "states_insufficiency": True},
        {**GOOD_JUDGE, "answer_type": "insufficient_evidence", "insufficiency_justified": True})
    check("refusal that cites related provisions: grader's 'insufficient' reading adopted, VERIFIED",
          status == "VERIFIED" and answer_type == "insufficient_evidence" and classification == "TRUE_INSUFFICIENT", reasons)
    status, reasons, answer_type, _ = grade(ANSWERABLE, {**CLEAN_CHECKS, "states_insufficiency": True}, GOOD_JUDGE)
    check("insufficiency phrase in a verified, complete answer ('not sufficient to rebut') -> grader's cited_answer, VERIFIED",
          status == "VERIFIED" and answer_type == "cited_answer", reasons)
    status, reasons, _, _ = grade(ANSWERABLE, CLEAN_CHECKS, {**GOOD_JUDGE, "answer_type": "partial_answer"})
    check("apparent answer that the grader finds incomplete -> NEEDS_REVIEW", "answer_type_disagreement" in reasons, reasons)
    status, reasons, _, _ = grade(ANSWERABLE, {**CLEAN_CHECKS, "verified_sources": 0, "states_insufficiency": True}, GOOD_JUDGE)
    check("grader calls an unverified refusal an answer -> NEEDS_REVIEW", "answer_type_disagreement" in reasons, reasons)
    two_statutes = [
        {"source_doc_id": "STATUTE-ipc-s261", "kind": "statute", "equivalence": "exact", "retrieved_doc_ids": ["STATUTE-ipc-s261"], "cited_doc_ids": ["STATUTE-ipc-s261"], "satisfied_by": "exact"},
        {"source_doc_id": "STATUTE-bns-s183", "kind": "statute", "equivalence": "exact", "retrieved_doc_ids": ["STATUTE-bns-s183"], "cited_doc_ids": [], "satisfied_by": "exact"},
    ]
    status, reasons, _, _ = grade(ANSWERABLE, {**CLEAN_CHECKS, "required_sources": two_statutes}, GOOD_JUDGE)
    check("comparison answer that cites only one of two required provisions -> NEEDS_REVIEW", "required_source_not_cited" in reasons, reasons)
    identical = "Whoever, fraudulently or with intent to cause loss to the Government, removes from any substance bearing any stamp"
    citations = [{"doc_id": "STATUTE-ipc-s261", "verified": True, "evidence_quotes": [identical]}]
    excerpts = [{"doc_id": "STATUTE-ipc-s261", "excerpt": identical + " ... three years"},
                {"doc_id": "STATUTE-bns-s183", "excerpt": identical + " ... three years"},
                {"doc_id": "STATUTE-bns-s185", "excerpt": "unrelated text about stamps"}]
    check("verbatim quote present in two identically worded provisions counts as citing both",
          quote_supported_ids(citations, excerpts) == {"STATUTE-ipc-s261", "STATUTE-bns-s183"}, quote_supported_ids(citations, excerpts))
    status, reasons, _, _ = grade(ANSWERABLE, CLEAN_CHECKS, {**GOOD_JUDGE, "concise": False})
    check("padded / repetitive answer -> NEEDS_REVIEW", status == "NEEDS_REVIEW" and "answer_not_concise" in reasons, reasons)

    def principle_checks(equivalence):
        rows = [{"source_doc_id": "NI138-1", "kind": "case_law", "equivalence": equivalence, "accepted_doc_count": 3,
                 "retrieved_doc_ids": [], "cited_doc_ids": [], "satisfied_by": None}]
        return {**CLEAN_CHECKS, "required_sources": rows, "seed_all_retrieved": False, "seed_retrieved": False}
    retrieved = [{"doc_id": "STATUTE-ni-act-s139", "source_type": "statute"}, {"doc_id": "NI138-999", "source_type": "case_law"}]
    checks = confirm_principle_equivalents(principle_checks("principle"), retrieved, {**GOOD_JUDGE, "judgment_excerpts_supporting_principle": [2]})
    check("principle authority satisfied by a grader-confirmed equivalent judgment",
          checks["seed_all_retrieved"] and checks["required_sources"][0]["satisfied_by"] == "grader_confirmed_equivalent")
    checks = confirm_principle_equivalents(principle_checks("principle"), retrieved, {**GOOD_JUDGE, "judgment_excerpts_supporting_principle": [1]})
    check("a statute excerpt cannot stand in for a judgment", not checks["seed_all_retrieved"])
    checks = confirm_principle_equivalents(principle_checks("exact"), retrieved, {**GOOD_JUDGE, "judgment_excerpts_supporting_principle": [2]})
    check("specific-judgment authority is never satisfied by another judgment", not checks["seed_all_retrieved"])

    for text, leaks in [
        ('Section 138 applies [1].<parameter name="citations">', True), ("See [SOURCE: STATUTE-ipc-s40]", True),
        ("The excerpt STATUTE-ipc-s40 says", True), ("### Short answer\nYes, under Section 138 of the NI Act [1].", False),
        ("An amount < Rs 5,000 is exempt [1].", False),
    ]:
        check(f"leak detector {'flags' if leaks else 'passes'}: {text[:40]!r}", bool(INTERNAL_LEAK.search(text)) == leaks)

    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
