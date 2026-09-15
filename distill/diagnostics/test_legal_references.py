"""
Deterministic checks for src/legal_references.py against the real corpus (no network, no LLM).
Expected doc_ids are only those the corpus itself contains; mapped counterparts are read from the
stored corresponds_to metadata, never asserted from outside knowledge.

Usage (from the repository root):
    .venv/bin/python distill/diagnostics/test_legal_references.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from db import get_documents_brief  # noqa: E402
from legal_references import expand_mappings, find_references, plan_retrieval  # noqa: E402

CASES = [
    ("Section 140 of the Negotiable Instruments Act, 1881", ["STATUTE-ni-act-s140"]),
    ("Section 141 NI Act", ["STATUTE-ni-act-s141"]),
    ("Section 10 of the Indian Evidence Act", ["STATUTE-iea-s10"]),
    ("Section 362 IPC", ["STATUTE-ipc-s362"]),
    ("Section 318 BNS", ["STATUTE-bns-s318"]),
    ("Section 142 BNSS", ["STATUTE-bnss-s142"]),
    ("IPC 420", ["STATUTE-ipc-s420"]),
    ("CrPC 438", ["STATUTE-crpc-s438"]),
    ("s. 65B of the Evidence Act", ["STATUTE-iea-s65b"]),
    ("Sections 10 and 11 of the Indian Evidence Act, 1872", ["STATUTE-iea-s10", "STATUTE-iea-s11"]),
    ("Section 138 read with Section 141 of the Negotiable Instruments Act, 1881", ["STATUTE-ni-act-s138", "STATUTE-ni-act-s141"]),
    ("the proviso to Section 372 Cr.P.C. (now Section 413 BNSS)", ["STATUTE-crpc-s372", "STATUTE-bnss-s413"]),
    ("Section 27 of the General Clauses Act and Section 114 of the Indian Evidence Act",
     ["STATUTE-general-clauses-act-s27", "STATUTE-iea-s114"]),
    ("Under Section 10 of the Indian Evidence Act, 1872, can the accused invoke Section 11 of the same Act?",
     ["STATUTE-iea-s10", "STATUTE-iea-s11"]),
    ("Section 2(1)(k) of the National Bank for Financing Infrastructure and Development Act, 2021",
     ["STATUTE-national-bank-financing-infrastructure-development-act-2021-s2"]),
    ("u/s 138 of the NI Act", ["STATUTE-ni-act-s138"]),
    ("Section 362 (Abduction) of the Indian Penal Code, 1860", ["STATUTE-ipc-s362"]),
    # Act named earlier in the same clause as the section.
    ("Under the Insolvency and Bankruptcy Code, 2016, an appeal lies to the NCLAT under Section 202, while under the Insurance Act, 1938, an appeal against an order of the Tribunal lies under Section 61A.",
     ["STATUTE-insolvency-bankruptcy-code-2016-s202", "STATUTE-insurance-act-1938-s61a"]),
    # A repeated section number keeps the Act it was first attached to.
    ("Section 106 of the Indian Evidence Act, 1872 deals with the burden of proving a fact especially within a person's knowledge. Which provision of the Bharatiya Sakshya Adhiniyam, 2023 corresponds to this old Section 106?",
     ["STATUTE-iea-s106"]),
    # Titles with a comma or no hyphen before the year, and Acts sharing a year-less name.
    ("Section 80 of the Income-tax Act, 2025", ["STATUTE-income-tax-act-2025-s80"]),
    ("Section 80 of the Income-tax Act 2025", ["STATUTE-income-tax-act-2025-s80"]),
    ("Section 80 of the Income Tax Act, 2025", ["STATUTE-income-tax-act-2025-s80"]),
    ("Section 80 of the Income-tax Act, 1961", ["STATUTE-income-tax-act-s80"]),
    ("How do Sections 80 and 81 of the Income-tax Act, 2025 operate together?",
     ["STATUTE-income-tax-act-2025-s80", "STATUTE-income-tax-act-2025-s81"]),
    ("Section 2 of the Special Court (Trial of Offences Relating to Transactions in Securities) Act, 1992",
     ["STATUTE-special-court-trial-offences-relating-transactions-securities-act-s2"]),
    # No explicit reference: nothing may be returned.
    ("What is the punishment for cheating under Indian law?", []),
    ("The accused paid a fine of Rs 5000 under the IPC within 15 days", []),
    ("Section 138 cheque bounce", []),
]


def mapped_from_metadata(doc_id):
    row = next(iter(get_documents_brief([doc_id])), None)
    entries = json.loads(row["metadata_json"] or "{}").get("corresponds_to") or [] if row else []
    return entries


def main():
    failures = 0
    for text, expected in CASES:
        got = [r.doc_id for r in find_references(text)]
        ok = got == expected
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {text!r}\n      expected={expected}\n      got     ={got}")

    print("\n--- mapping expansion (targets must come from stored corresponds_to) ---")
    for text in ["Section 362 IPC", "Section 138 BNS", "Section 210 CrPC", "Section 114 of the Indian Evidence Act",
                 "Section 233 BNSS", "Section 119 BSA"]:
        references = find_references(text)
        mapped = expand_mappings(references)
        stored = [(e.get("act"), e.get("section"), e.get("relation")) for r in references for e in mapped_from_metadata(r.doc_id)]
        from_metadata = all(any(m.doc_id.endswith(f"-{a}-s{str(s).lower()}") for a, s, _ in stored) for m in mapped)
        ok = bool(mapped) and from_metadata
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {text!r} -> {[m.doc_id for m in mapped]} (stored: {stored})")

    print("\n--- ambiguous Act name: both candidates, neither required ---")
    references = find_references("Section 80 of the Income-tax Act")
    plan = plan_retrieval("Section 80 of the Income-tax Act")
    ok = [r.doc_id for r in references] == ["STATUTE-income-tax-act-s80", "STATUTE-income-tax-act-2025-s80"] \
        and all(r.ambiguous for r in references) and not plan.requirements
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  refs={[(r.doc_id, r.ambiguous) for r in references]} requirements={plan.requirements}")

    print("\n--- retrieval plans ---")
    plan_cases = [
        ("Which provision of the Bharatiya Nyaya Sanhita, 2023 corresponds to Section 362 (Abduction) of the Indian Penal Code, 1860?",
         # Two Acts named and a section cited: no Act-scoped search.
         [("STATUTE-ipc-s362", "explicit_reference"), ("STATUTE-bns-s138", "mapped_counterpart")], []),
        ("Which section of the Bharatiya Nagarik Suraksha Sanhita, 2023 deals with the form of summons, and which provision of the Code of Criminal Procedure, 1973 did it replace?",
         [], []),
        ("What does Section 138 BNS say about abduction?", [("STATUTE-bns-s138", "explicit_reference")], []),
        ("Under Section 139 of the NI Act, how have courts treated a bare denial by the accused?",
         [("STATUTE-ni-act-s139", "explicit_reference"), (None, "case_law_authority")], []),
        ("Under the National Bank for Financing Infrastructure and Development Act, 2021, how is infrastructure defined?",
         [], ["national-bank-financing-infrastructure-development-act-2021"]),
        ("What does the Code of Criminal Procedure say about the place of trial for extortion?", [], ["crpc"]),
    ]
    for text, expected_requirements, expected_scope in plan_cases:
        plan = plan_retrieval(text)
        got = [(r.doc_id, r.reason) for r in plan.requirements]
        ok = got == expected_requirements and plan.act_scope == expected_scope
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {text[:80]!r}\n      requirements={got} act_scope={plan.act_scope}")

    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
