"""
Builds data/distill/pilot/retrieval_diagnostic.json from the probe outputs plus the manual classification
of the 15 needs_review examples. Read-only with respect to the pilot files and src/.

Failure classes: A exact section reference, B Act name, C old->new mapping, D multiple authorities,
E case law, F semantic mismatch, G keyword/FTS, H reranking/fusion, I chunking/metadata,
J question generation / grading, K other (e.g. teacher quote fidelity).

Usage (from the repository root, after retrieval_probe.py and rerank_ablation.py):
    .venv/bin/python distill/diagnostics/build_diagnostic_json.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "data" / "distill" / "pilot"
DIAG = PILOT / "diagnostics"

CLASSIFICATION = {
    "q-3185dbed0d6d": dict(
        primary="H", secondary=["I"], genuine=True, true_insufficient=False, false_insufficient=True,
        evidence="Section 2 was semantic chunk rank 8 (score 0.693) and keyword rank 7, inside the 15-candidate pool, "
                 "but the 0.75/0.25 rerank kept five other chunks of the same Act. Act-filtered semantic search and "
                 "RRF fusion (ablation D) both return s2. The embedded chunk has no 'Definitions' heading or Act title.",
        fix="Rank fusion that keeps keyword evidence (RRF, ablation D recovers it)."),
    "q-520bf8984839": dict(
        primary="I", secondary=["H"], genuine=True, true_insufficient=False, false_insufficient=True,
        evidence="Section 2 is 3,518 chars split into 4 chunks; the 'infrastructure' clause sits in a later chunk that "
                 "carries neither the Act title nor the heading (semantic rank 12, score 0.542; keyword rank 23). "
                 "RRF does not recover it; only oracle 'Act + Section 2 + Definitions' queries or act-filtered search do. "
                 "Teacher cited s3 and said the definition was absent.",
        fix="Include Act title + section number + heading in the embedded/scored chunk text (needs re-embedding; "
            "defer), or act-scoped retrieval when an Act is named."),
    "q-bc93aeb2040e": dict(
        primary="K", secondary=[], genuine=False, true_insufficient=False, false_insufficient=False,
        evidence="Seed s40 retrieved at rank 2. Flag was some_quotes_unmatched: the s13 quote is verbatim for 59 of 63 "
                 "words then splices text across a gap. Teacher quote fidelity, not retrieval.",
        fix="None for retrieval. Treat single spliced quotes as teacher-fidelity review items."),
    "q-db2f8b89a1b6": dict(
        primary="H", secondary=["F"], genuine=True, true_insufficient=False, false_insufficient=False,
        evidence="Section 32 was keyword rank 1 and semantic rank 6 (0.655), in the pool, but dropped by rerank; its "
                 "BM25 rank-1 signal was discarded because the doc was already a semantic hit. Teacher then answered "
                 "from s45 (wrong provision) with verified citations - a confident wrong answer, not a refusal. "
                 "RRF puts s32 at rank 1.",
        fix="Rank fusion that keeps keyword rank (RRF). Grader should flag answers when the seed provision is absent."),
    "q-835e1e9f9fe5": dict(
        primary="A", secondary=["F", "I"], genuine=True, true_insufficient=False, false_insufficient=True,
        evidence="Question names 'Section 10' and 'Section 11 of the Indian Evidence Act, 1872'. Neither is in the "
                 "semantic top 100 (the query drifts to NI Act judgments about accused/trial); keyword ranks 87 and "
                 "none. Embedded text has no section numbers, so the explicit reference cannot match. Parsing the "
                 "reference (Act + section numbers) resolves both doc_ids directly.",
        fix="Explicit section-reference resolution: parse 'Section N of <Act>' and inject those sections."),
    "q-6006b8fb9ef6": dict(
        primary="H", secondary=["F", "D"], genuine=True, true_insufficient=False, false_insufficient=True,
        evidence="Fact pattern names only the CrPC, not sections. s181 was keyword rank 1 / semantic rank 12, dropped "
                 "by rerank; s180 was keyword rank 12 only (semantic not in top 100). RRF recovers s181 but not s180. "
                 "Teacher answered partially via s182/s223.",
        fix="RRF fusion (recovers s181); s180 needs query expansion or act-scoped retrieval - not solved by tested variants."),
    "q-0e66cd570330": dict(
        primary="H", secondary=["F"], genuine=True, true_insufficient=False, false_insufficient=True,
        evidence="BNS s218 was semantic chunk rank 4 (0.608), keyword rank 9, yet excluded from the final 5: the "
                 "lexical-overlap term on a long fact-pattern question re-ordered it below CGST/BNSS chunks. "
                 "Semantic order alone (ablation B) and RRF (D) both include it.",
        fix="RRF fusion; stop letting raw word-overlap ratio override retrieval rank."),
    "q-395ec4bb9c7e": dict(
        primary="K", secondary=[], genuine=False, true_insufficient=False, false_insufficient=False,
        evidence="Both CrPC s210 and BNSS s233 retrieved at ranks 1-2. Flag was some_quotes_unmatched: quote verbatim "
                 "for 49 of 68 words then spliced. Not retrieval.",
        fix="None for retrieval."),
    "q-c4dcb3eb2ee9": dict(
        primary="H", secondary=["C", "F"], genuine=True, true_insufficient=False, false_insufficient=True,
        evidence="IPC s362 and BNS s138 were keyword ranks 1 and 2 but semantic ranks 55 and 67 (20-word sections vs a "
                 "'which provision corresponds' question). As keyword-only hits their rerank ceiling is 0.25 versus "
                 "~0.4+ for semantic hits, so both were dropped. corresponds_to data exists (IPC s362 -> BNS s138, "
                 "near-identical) but retrieval never reads it. Mapping expansion from the parsed IPC reference "
                 "recovers both; RRF alone recovers only IPC s362.",
        fix="RRF fusion + resolve explicit reference + expand via corresponds_to."),
    "q-89d14510bd1b": dict(
        primary="J", secondary=["E"], genuine=False, true_insufficient=False, false_insufficient=False,
        evidence="Question states a principle, not the case. The principle ('within 15 days of receipt of the "
                 "summons') appears in 39/194 judgments; seed judgment was semantic rank 61. Teacher gave a correct "
                 "cited answer from equivalent judgments. The seed_source_not_retrieved check is invalid for "
                 "principle-level case questions. Searching by case name retrieves it at rank 1.",
        fix="Case-law questions must either name the case or be graded on principle support, not seed identity."),
    "q-ae393c6b3d7b": dict(
        primary="J", secondary=["E", "K"], genuine=False, true_insufficient=False, false_insufficient=False,
        evidence="Principle-level question (S.27 General Clauses Act / S.114 Evidence Act presumption of service) - "
                 "present in ~58-59/194 judgments; seed semantic rank 69. Correct 3-citation answer from equivalent "
                 "judgments. Secondary flag cited_source_not_referenced_inline is teacher formatting.",
        fix="Same as q-89d14510bd1b."),
    "q-21a98fabade6": dict(
        primary="K", secondary=[], genuine=False, true_insufficient=False, false_insufficient=False,
        evidence="Seed judgment retrieved at rank 1. Flag was some_quotes_unmatched: quote verbatim for 38 of 44 words "
                 "then spliced. Not retrieval.",
        fix="None for retrieval."),
    "q-cee5a99865bb": dict(
        primary="D", secondary=["A", "H", "J"], genuine=True, true_insufficient=False, false_insufficient=True,
        evidence="Needs NI Act s141 and a judgment on victim appeals under the proviso to s372 CrPC. s141 never enters "
                 "the semantic top 100 (keyword rank 163); the case-specific judgment was keyword rank 2 / semantic 16 "
                 "- just outside the semantic pool and dropped as keyword-only. Only 11/194 judgments discuss the "
                 "proviso. One query, one pool, top 5 cannot cover both a statute and a narrow judgment. RRF recovers "
                 "the judgment; reference parsing recovers s141. Generator answer_hint also contains leaked tool "
                 "markup ('</answer_hint></invoke>').",
        fix="RRF + explicit reference resolution; later, per-authority sub-queries for multi-authority questions."),
    "q-c69f7823801d": dict(
        primary="A", secondary=["D", "J"], genuine=True, true_insufficient=False, false_insufficient=False,
        evidence="Question names 'Section 140 of the Negotiable Instruments Act, 1881'; s140 not in semantic top 100 "
                 "and keyword rank 149 (long question floods the OR query). The judgment half is principle-level "
                 "(39 equivalents) and was answered correctly from equivalents, but s140 was never available to cite.",
        fix="Explicit section-reference resolution (recovers s140)."),
    "q-69d6210ebe23": dict(
        primary="J", secondary=[], genuine=False, true_insufficient=False, false_insufficient=False,
        evidence="Generated as insufficient_evidence with a hint claiming the term is not stated, but IPC s40 says "
                 "'imprisonment for a term of six months or upwards'. Retrieved at rank 1 (keyword 1, semantic 5). "
                 "Teacher answered correctly with a verified citation; the checker correctly surfaced the label "
                 "mismatch. The question is answerable; the label is wrong.",
        fix="Validate insufficient_evidence questions against the seed text before use; relabel as answerable "
            "in a future run (old pilot record left unchanged)."),
}


def main():
    probe = json.loads((DIAG / "probe_results.json").read_text())
    ablation = json.loads((DIAG / "rerank_ablation.json").read_text())
    by_id = {e["id"]: e for e in probe["all_examples"]}
    ablation_by_id = {r["id"]: r for r in ablation["rows"]}
    questions = {json.loads(l)["id"]: json.loads(l) for l in (PILOT / "questions.jsonl").read_text().splitlines() if l.strip()}

    examples = []
    for qid, c in CLASSIFICATION.items():
        e = by_id[qid]
        ranks = {d: r for d, r in e["pilot_intended_ranks"].items()}
        stages = e["rerun"]["intended"]
        examples.append({
            "id": qid,
            "question": questions[qid]["question"],
            "category": e["category"],
            "status_reasons": e["reasons"],
            "intended_source_ids": e["intended"],
            "retrieved_source_ids": e["pilot_retrieved_ids"],
            "intended_source_retrieved": {d: r is not None for d, r in ranks.items()},
            "rank": ranks,
            "stage_ranks": {d: {k: stages[d][k] for k in ("semantic_rank", "semantic_score", "keyword_rank",
                                                        "in_candidate_pool", "pool_source", "dropped_by_rerank")}
                            for d in e["intended"]},
            "rrf_ablation_hits": ablation_by_id[qid]["strategies"]["D_rrf_pool15_1_chunk_per_doc"]["hits"],
            "genuine_retrieval_failure": c["genuine"],
            "primary_failure_type": c["primary"],
            "secondary_failure_types": c["secondary"],
            "true_insufficient": c["true_insufficient"],
            "false_insufficient": c["false_insufficient"],
            "evidence": c["evidence"],
            "recommended_fix": c["fix"],
        })

    output = {
        "run": "pilot",
        "generated_by": "distill/diagnostics/build_diagnostic_json.py",
        "failure_classes": {"A": "exact section reference", "B": "Act name", "C": "old->new mapping",
                            "D": "multiple authorities", "E": "case law", "F": "semantic mismatch",
                            "G": "keyword/FTS", "H": "reranking/fusion", "I": "chunking/metadata",
                            "J": "question generation / grading", "K": "other (teacher quote fidelity)"},
        "retrieval_settings": probe["settings"],
        "rerun_reproduces_pilot_top5": f"{sum(e['rerun_matches_pilot'] for e in probe['all_examples'])}/50",
        "ablation_summary": ablation["summary"],
        "verified_insufficient_example": {
            "id": "q-fc0be1b06670", "split": "train", "classification": "TRUE_INSUFFICIENT",
            "evidence": "LLP Act s12 retrieved at rank 1 with four other LLP Act sections; s12 sets the 14-day duty but "
                        "states no consequence for Registrar delay, and the teacher said so with a verified citation. "
                        "Caveat: retrieval covered 5 sections of the Act, not the whole Act.",
        },
        "examples": examples,
    }
    (PILOT / "retrieval_diagnostic.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))

    short = lambda d: d.replace("STATUTE-", "").replace("special-court-trial-offences-relating-transactions-securities-act", "spl-court-securities").replace("national-bank-financing-infrastructure-development-act-2021", "nabfid-2021").replace("legal-metrology-act-2009", "legal-metrology")
    print("| id | category | intended | pilot top-5 | intended retrieved (rank) | sem / kw rank | in pool, dropped by rerank | primary | secondary |")
    print("|---|---|---|---|---|---|---|---|---|")
    for x in examples:
        intended = "<br>".join(short(d) for d in x["intended_source_ids"])
        top5 = ", ".join(short(d) for d in x["retrieved_source_ids"])
        got = "<br>".join(f"{'yes' if r else 'no'}{f' ({r})' if r else ''}" for r in x["rank"].values())
        st = "<br>".join(f"{s['semantic_rank'] or '>100'} / {s['keyword_rank'] or '>200'}" for s in x["stage_ranks"].values())
        dropped = "<br>".join("yes" if s["dropped_by_rerank"] else ("n/a" if x["rank"][d] else "no (never in pool)") for d, s in x["stage_ranks"].items())
        print(f"| {x['id']} | {x['category']} | {intended} | {top5} | {got} | {st} | {dropped} | {x['primary_failure_type']} | {', '.join(x['secondary_failure_types']) or '-'} |")


if __name__ == "__main__":
    main()
