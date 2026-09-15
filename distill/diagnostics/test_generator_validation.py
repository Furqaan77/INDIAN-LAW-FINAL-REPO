"""
Offline tests of the question generator's acceptance gates (stubbed Claude calls, real corpus, no network).

Usage (from the repository root):
    .venv/bin/python distill/diagnostics/test_generator_validation.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "distill"))

from build_questions import Corpus, names_case, process_candidate, statute_passage  # noqa: E402

failures = []


def check(name, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {name}{('  — ' + str(detail)) if detail else ''}")
    if not condition:
        failures.append(name)


def stub(question=None, review=None, answerability=None):
    def ask(tool, system, user, **kwargs):
        if tool["name"] == "write_question":
            return question
        if tool["name"] == "review_question":
            return review
        return answerability
    return ask


def judgment_seed(corpus, doc_id, anchor, case_law_type):
    judgment = corpus.judgments_by_id[doc_id]
    start = judgment["full_text"].find(anchor)
    text = judgment["full_text"][max(0, start - 600): start + 900]
    passage = {"doc_id": doc_id, "label": judgment["title"], "section": None, "text": text, "kind": "case_law", "title": judgment["title"]}
    return {"passages": [passage], "doc_ids": [doc_id], "case_law_type": case_law_type}, text


def main():
    corpus = Corpus()
    no_retrieval = lambda q: []  # noqa: E731

    print("--- insufficient_evidence ---")
    ipc40 = corpus.statutes["STATUTE-ipc-s40"]
    seed = {"passages": [statute_passage(ipc40)], "doc_ids": [ipc40["doc_id"]], "case_law_type": None}
    q = {"question": "Under Section 40 of the Indian Penal Code, 1860, what minimum term of imprisonment must a special or local law prescribe for sections 141, 176 and 177?", "answer_hint": "not stated", "evidence_quotes": []}
    outcome = process_candidate("insufficient_evidence", seed, corpus, retrieve=no_retrieval, ask=stub(
        question=q, answerability={"answerable": True, "supporting_quote": "punishable under such law with imprisonment for a term of six months or upwards"}))
    check("IPC s40 'insufficient' question rejected: the corpus answers it", not outcome["accepted"] and outcome["reason"] == "insufficient_label_rejected:answerable", outcome["reason"])
    outcome = process_candidate("insufficient_evidence", seed, corpus, retrieve=no_retrieval, ask=stub(
        question={**q, "question": "Under the Indian Penal Code, 1860, which notification lists the special laws covered by Section 40?"},
        answerability={"answerable": False, "supporting_quote": ""}))
    check("genuinely unanswered question accepted as TRUE_INSUFFICIENT",
          outcome["accepted"] and outcome["record"]["insufficiency_check"]["classification"] == "TRUE_INSUFFICIENT", outcome["reason"])

    print("\n--- statute questions ---")
    s32 = corpus.statutes["STATUTE-legal-metrology-act-2009-s32"]
    seed = {"passages": [statute_passage(s32)], "doc_ids": [s32["doc_id"]], "case_law_type": None}
    quote = "shall be punished with fine which may extend to twenty thousand rupees"
    good_q = {"question": "What punishment does the Legal Metrology Act, 2009 prescribe for failing to submit a weight or measure model for approval?",
              "answer_hint": "fine up to twenty thousand rupees", "evidence_quotes": [{"passage": 1, "quote": quote}]}
    good_review = {"answerable": True, "uses_every_passage": True, "ambiguous": False, "well_formed": True, "principle_phrase_is_legal_principle": True, "supporting_quotes": [{"passage": 1, "quote": quote}], "problem": ""}
    outcome = process_candidate("punishment", seed, corpus, ask=stub(question=good_q, review=good_review))
    check("valid question accepted with intended chunk identified",
          outcome["accepted"] and outcome["record"]["seed"]["authorities"][0]["intended_chunk_ids"] == ["STATUTE-legal-metrology-act-2009-s32_chunk0"],
          outcome.get("record", {}).get("seed", {}).get("authorities") if outcome["accepted"] else outcome["reason"])
    outcome = process_candidate("punishment", seed, corpus, ask=stub(
        question={**good_q, "evidence_quotes": [{"passage": 1, "quote": "shall be punished with imprisonment for life"}]}, review=good_review))
    check("evidence quote not in the source -> rejected", outcome["reason"] == "evidence_quotes_not_verbatim", outcome["reason"])
    outcome = process_candidate("punishment", seed, corpus, ask=stub(question=good_q, review={**good_review, "ambiguous": True}))
    check("reviewer finds ambiguity -> rejected", outcome["reason"] == "reviewer_ambiguous", outcome["reason"])
    outcome = process_candidate("punishment", seed, corpus, ask=stub(question=good_q, review={**good_review, "answerable": False}))
    check("reviewer finds it unanswerable -> rejected", "reviewer_not_answerable" in outcome["reason"], outcome["reason"])
    outcome = process_candidate("punishment", seed, corpus, ask=stub(question={**good_q, "question": good_q["question"] + "</question>"}, review=good_review))
    check("tool markup in question -> rejected", outcome["reason"] == "markup_in_question", outcome["reason"])
    outcome = process_candidate("punishment", seed, corpus, ask=stub(question=good_q, review={**good_review, "well_formed": False}))
    check("reviewer finds question convoluted / leading -> rejected", outcome["reason"] == "reviewer_not_well_formed", outcome["reason"])
    outcome = process_candidate("punishment", seed, corpus, ask=stub(question={**good_q, "question": "Q" * 460}, review=good_review))
    check("over-long non-fact-pattern question -> rejected", outcome["reason"] == "bad_length", outcome["reason"])

    print("\n--- multiple sections ---")
    s10, s11 = corpus.statutes["STATUTE-iea-s10"], corpus.statutes["STATUTE-iea-s11"]
    seed = {"passages": [statute_passage(s10), statute_passage(s11)], "doc_ids": [s10["doc_id"], s11["doc_id"]], "case_law_type": None}
    q10 = "anything said, done or written by any one of such persons in reference to their common intention"
    q11 = "if they are inconsistent with any fact in issue or relevant fact"
    mq = {"question": "How do Sections 10 and 11 of the Indian Evidence Act, 1872 each make facts relevant?", "answer_hint": "both",
          "evidence_quotes": [{"passage": 1, "quote": q10}, {"passage": 2, "quote": q11}]}
    mreview = {"answerable": True, "uses_every_passage": True, "ambiguous": False, "well_formed": True, "principle_phrase_is_legal_principle": True, "problem": "",
               "supporting_quotes": [{"passage": 1, "quote": q10}, {"passage": 2, "quote": q11}]}
    outcome = process_candidate("multiple_sections", seed, corpus, ask=stub(question=mq, review=mreview))
    check("two required sections recorded as two authorities", outcome["accepted"] and len(outcome["record"]["seed"]["authorities"]) == 2, outcome["reason"])
    outcome = process_candidate("multiple_sections", seed, corpus, ask=stub(question={**mq, "evidence_quotes": [{"passage": 1, "quote": q10}]}, review=mreview))
    check("evidence for only one of two passages -> rejected", outcome["reason"] == "evidence_quotes_not_verbatim", outcome["reason"])
    outcome = process_candidate("multiple_sections", seed, corpus, ask=stub(question=mq, review={**mreview, "uses_every_passage": False}))
    check("reviewer says one passage is enough -> rejected", "reviewer_does_not_need_every_passage" in outcome["reason"], outcome["reason"])

    print("\n--- case law: specific judgment vs legal principle ---")
    seed, text = judgment_seed(corpus, "NI138-37547942", "General Clauses", "specific_judgment")
    sentence = text[text.find("General Clauses") - 60: text.find("General Clauses") + 60]
    words = " ".join(sentence.split()[1:-1])
    cq = {"question": "In Rachit Chawla v. Gurdeep Singh Bhatia, how did the court treat service of the demand notice?", "answer_hint": "presumption",
          "evidence_quotes": [{"passage": 1, "quote": words}], "names_specific_case": True}
    creview = {"answerable": True, "uses_every_passage": True, "ambiguous": False, "well_formed": True, "principle_phrase_is_legal_principle": True, "supporting_quotes": [{"passage": 1, "quote": words}], "problem": ""}
    check("party names detected in a question naming the case", names_case(cq["question"], seed["passages"][0]["title"]))
    outcome = process_candidate("case_law", seed, corpus, ask=stub(question=cq, review=creview))
    check("specific-judgment question naming the parties -> exact authority",
          outcome["accepted"] and outcome["record"]["seed"]["authorities"][0]["equivalence"] == "exact", outcome["reason"])
    outcome = process_candidate("case_law", seed, corpus, ask=stub(question={**cq, "question": "How do courts treat service of a demand notice sent by registered post?"}, review=creview))
    check("specific-judgment question without party names -> rejected", outcome["reason"] == "specific_case_question_does_not_name_parties", outcome["reason"])

    seed, text = judgment_seed(corpus, "NI138-37033830", "within 15 days of receipt of the summons", "legal_principle")
    phrase_start = text.lower().find("within 15 days of receipt of the summons")
    phrase = text[phrase_start: phrase_start + len("within 15 days of receipt of the summons")]
    pq = {"question": "If an accused does not pay the cheque amount within 15 days of receiving the court summons, can he still dispute service of the demand notice?",
          "answer_hint": "no", "evidence_quotes": [{"passage": 1, "quote": phrase}], "principle_phrase": phrase, "names_specific_case": False}
    preview = {"answerable": True, "uses_every_passage": True, "ambiguous": False, "well_formed": True, "principle_phrase_is_legal_principle": True, "supporting_quotes": [{"passage": 1, "quote": phrase}], "problem": ""}
    outcome = process_candidate("case_law", seed, corpus, ask=stub(question=pq, review=preview))
    equivalents = len(outcome["record"]["seed"]["authorities"][0]["doc_ids"]) if outcome["accepted"] else 0
    check("principle question -> every judgment stating the principle accepted", outcome["accepted"] and equivalents > 1, f"equivalent judgments={equivalents}")
    outcome = process_candidate("case_law", seed, corpus, ask=stub(question={**pq, "question": "In Deutsche Bank AG v. Abhishek Chuhan, can the accused dispute service after 15 days?"}, review=preview))
    check("principle question that names the case -> rejected (must be classified as specific)", outcome["reason"] == "principle_question_names_the_case", outcome["reason"])
    outcome = process_candidate("case_law", seed, corpus, ask=stub(question={**pq, "principle_phrase": "courts always presume service of notice"}, review=preview))
    check("paraphrased principle phrase -> rejected", outcome["reason"] == "principle_phrase_not_verbatim", outcome["reason"])
    outcome = process_candidate("case_law", seed, corpus, ask=stub(question=pq, review={**preview, "principle_phrase_is_legal_principle": False}))
    check("boilerplate phrase that is not a legal principle -> rejected", outcome["reason"] == "reviewer_principle_not_a_legal_principle", outcome["reason"])

    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
