"""
Fresh retrieval-only evaluation set (independent of the 50-question distillation pilot).

No LLM is called and no answers are produced: each item is a question, a category, the intended
source doc_id(s) and the intended chunk id(s). Everything is grounded in the corpus:
  * templated items are generated deterministically from statute metadata and the corpus's own
    old/new correspondence data;
  * authored items (fact patterns, principle-based case-law questions, etc.) live in
    authored_questions.json and must name a verbatim `evidence_phrase` from each intended source;
    `build` rejects any item whose phrase is not found in the source.

Sources are sampled with a fixed seed and exclude every seed document of the pilot.

Usage (from the repository root):
    .venv/bin/python distill/diagnostics/build_fresh_eval.py sample   # writes sources_sample.json
    .venv/bin/python distill/diagnostics/build_fresh_eval.py build    # writes questions.jsonl
"""
import argparse
import hashlib
import html
import json
import random
import re
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "distill"))

from common import read_jsonl  # noqa: E402  (also puts src/ on sys.path)
from db import get_connection  # noqa: E402
from ingest_statutes import make_statute_doc_id  # noqa: E402

OUT = ROOT / "data" / "distill" / "retrieval_eval" / "fresh_v1"
PILOT_QUESTIONS = ROOT / "data" / "distill" / "pilot" / "questions.jsonl"
SAMPLE_SEED = "fresh-retrieval-eval-v1"

HIGH_VALUE_ACTS = [
    "ipc", "bns", "crpc", "bnss", "iea", "bsa", "ni-act", "contract-act", "companies-act", "cpc",
    "consumer-protection-act", "hindu-marriage-act", "specific-relief-act", "limitation-act", "arbitration-act",
    "income-tax-act", "income-tax-act-2025", "hindu-succession-act-1956", "partnership-act", "sale-of-goods-act",
    "dowry-prohibition-act-1961", "pocso-act", "information-technology-act", "motor-vehicles-act",
]
GENERIC_HEADING = re.compile(
    r"short title|definition|interpretation|power to make rules|\brules\b|regulations|repeal|saving|commencement|"
    r"\bextent\b|protection of action|good faith|remove difficult|delegation|laid before|amendment of|transitional",
    re.IGNORECASE,
)
OMITTED = re.compile(r"^\W*(?:omitted|repealed)", re.IGNORECASE)
GOOD_RELATIONS = {"near-identical", "official", "close"}


def load_corpus():
    conn = get_connection()
    try:
        statutes = conn.execute(
            "SELECT doc_id, full_text, metadata_json FROM documents WHERE source_type='statute' ORDER BY doc_id"
        ).fetchall()
        judgments = conn.execute(
            "SELECT doc_id, title, court, date, full_text FROM documents WHERE source_type='case_law' ORDER BY doc_id"
        ).fetchall()
    finally:
        conn.close()
    docs = {}
    for row in statutes:
        meta = json.loads(row["metadata_json"] or "{}")
        docs[row["doc_id"]] = {
            "doc_id": row["doc_id"], "act_id": meta.get("act_id"), "act_title": meta.get("act_title"),
            "section": meta.get("section_number"), "heading": meta.get("section_heading") or "",
            "text": html.unescape(row["full_text"] or "").strip(), "corresponds_to": meta.get("corresponds_to") or [],
        }
    cases = {r["doc_id"]: {**dict(r), "full_text": html.unescape(r["full_text"] or "")} for r in judgments}
    return docs, cases


def pilot_seed_ids():
    return {d for q in read_jsonl(PILOT_QUESTIONS) for d in q["seed"]["doc_ids"]}


def substantive(doc, low=200, high=2500):
    return low <= len(doc["text"]) <= high and not OMITTED.match(doc["text"]) and not GENERIC_HEADING.search(doc["heading"])


def sample(args):
    rng = random.Random(SAMPLE_SEED)
    docs, cases = load_corpus()
    excluded = pilot_seed_ids()
    used = set(excluded)

    def pick(pool, n):
        pool = [d for d in pool if d["doc_id"] not in used]
        chosen = rng.sample(pool, min(n, len(pool)))
        used.update(d["doc_id"] for d in chosen)
        return chosen

    high_value = [d for d in docs.values() if d["act_id"] in HIGH_VALUE_ACTS and substantive(d)]
    punishing = [d for d in high_value if "punish" in d["heading"].lower() or "shall be punished" in d["text"] or "liable" in d["text"]]
    definitions = [
        d for d in docs.values()
        if d["act_id"] in HIGH_VALUE_ACTS and "definition" in d["heading"].lower() and d["doc_id"] not in excluded
    ]

    mapped = []
    for doc in docs.values():
        if doc["act_id"] not in {"ipc", "crpc", "iea"} or not substantive(doc):
            continue
        for link in doc["corresponds_to"]:
            if not isinstance(link, dict) or link.get("relation") not in GOOD_RELATIONS:
                continue
            target = docs.get(make_statute_doc_id(link.get("act", ""), link.get("section", "")))
            if target and substantive(target) and doc["doc_id"] not in excluded and target["doc_id"] not in excluded:
                mapped.append((doc, target, link.get("relation")))
                break

    well_formed = [
        c for c in cases.values()
        if len(c["full_text"]) > 6000 and "..." not in (c["title"] or "") and re.search(r"\bvs?\.?\s+\w", c["title"] or "")
        and not re.match(r"^(CT CASES|CC|Crl|CR)\b", c["title"] or "", re.IGNORECASE) and c["doc_id"] not in excluded
    ]

    def passage(case, size=1400):
        text = case["full_text"]
        start = rng.randint(int(len(text) * 0.25), max(int(len(text) * 0.25), int(len(text) * 0.8) - size))
        start = text.find(". ", start) + 2
        return text[start:start + size]

    selection = {
        "act_section_query": [strip(d) for d in pick(high_value, 8)],
        "fact_pattern": [strip(d) for d in pick(punishing, 10)],
        "definition_without_number": [strip(d, 2600) for d in pick(definitions, 6)],
        "exact_section_reference": [strip(d, 300) for d in pick(high_value, 10)],
        "multiple_sections_seed": [strip(d, 300) for d in pick(high_value, 6)],
        "old_new_law": [
            {"old": strip(o, 300), "new": strip(n, 300), "relation": rel}
            for o, n, rel in rng.sample(mapped, min(14, len(mapped)))
        ],
        "ni_act_core": [strip(docs[make_statute_doc_id("ni-act", s)], 1200)
                        for s in ["138", "139", "140", "141", "142", "143A", "145", "147", "148"]
                        if make_statute_doc_id("ni-act", s) in docs and make_statute_doc_id("ni-act", s) not in excluded],
        "case_passages": [
            {"doc_id": c["doc_id"], "title": c["title"], "passage": passage(c)} for c in rng.sample(well_formed, 14)
        ],
        "case_named": [{"doc_id": c["doc_id"], "title": c["title"]} for c in rng.sample(well_formed, 6)],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sources_sample.json").write_text(json.dumps(selection, indent=2, ensure_ascii=False))
    print("excluded pilot seed docs:", len(excluded))
    for key, items in selection.items():
        print(key, len(items))


def strip(doc, limit=1200):
    return {"doc_id": doc["doc_id"], "act_id": doc["act_id"], "act_title": doc["act_title"], "section": doc["section"],
            "heading": doc["heading"], "text": doc["text"][:limit]}


# ---------------------------------------------------------------- build

ABBREVIATION = {"ipc": "IPC", "bns": "BNS", "crpc": "CrPC", "bnss": "BNSS", "bsa": "BSA", "ni-act": "NI Act"}


def norm(text):
    return " ".join(re.findall(r"[a-z0-9]+", html.unescape(text or "").lower()))


def plain(title):
    return re.sub(r"^The\s+", "", title or "")


@lru_cache(maxsize=None)
def chunks_of(doc_id):
    from vector_store import get_vector_store
    got = get_vector_store().collection.get(where={"doc_id": doc_id}, include=["documents", "metadatas"])
    return [(meta.get("chunk_id"), norm(text)) for meta, text in zip(got["metadatas"], got["documents"])]


def chunks_with_phrase(doc_id, phrase):
    target = norm(phrase)
    hits = [cid for cid, text in chunks_of(doc_id) if target in text]
    if not hits:  # phrase crosses a chunk boundary: accept chunks holding its opening words
        opening = " ".join(target.split()[:8])
        hits = [cid for cid, text in chunks_of(doc_id) if opening in text]
    return hits


def statute_authority(docs, doc_id, phrase=None):
    doc = docs.get(doc_id)
    if doc is None:
        raise ValueError(f"unknown statute {doc_id}")
    if phrase is None:
        chunk_ids = [cid for cid, _ in chunks_of(doc_id)]
    else:
        if norm(phrase) not in norm(doc["text"]):
            raise ValueError(f"evidence phrase not in {doc_id}: {phrase!r}")
        chunk_ids = chunks_with_phrase(doc_id, phrase)
    if not chunk_ids:
        raise ValueError(f"no chunk found for {doc_id}")
    return {"label": doc_id, "doc_ids": [doc_id], "kind": "statute", "equivalence": "exact",
            "intended_chunk_ids": chunk_ids, "evidence_phrase": phrase}


def principle_authority(cases, source_doc_id, phrase):
    target = norm(phrase)
    equivalents = sorted(d for d, c in cases.items() if target in norm(c["full_text"]))
    if source_doc_id not in equivalents:
        raise ValueError(f"principle phrase not in its source judgment {source_doc_id}: {phrase!r}")
    chunk_ids = [cid for d in equivalents for cid in chunks_with_phrase(d, phrase)]
    return {"label": f"principle:{source_doc_id}", "doc_ids": equivalents, "kind": "case_law", "equivalence": "principle",
            "intended_chunk_ids": chunk_ids, "evidence_phrase": phrase, "source_doc_id": source_doc_id}


def case_authority(cases, doc_id):
    if doc_id not in cases:
        raise ValueError(f"unknown judgment {doc_id}")
    return {"label": doc_id, "doc_ids": [doc_id], "kind": "case_law", "equivalence": "exact",
            "intended_chunk_ids": [cid for cid, _ in chunks_of(doc_id)]}


def next_substantive(docs, doc):
    def key(d):
        match = re.match(r"(\d+)\s*([A-Za-z]*)", str(d["section"] or ""))
        return (int(match.group(1)), match.group(2).upper()) if match else (10 ** 9, "")
    same_act = sorted((d for d in docs.values() if d["act_id"] == doc["act_id"]), key=key)
    index = next(i for i, d in enumerate(same_act) if d["doc_id"] == doc["doc_id"])
    return next((d for d in same_act[index + 1:index + 6] if substantive(d, 120, 4000)), None)


def templated(selection, docs, cases):
    items = []
    exact_templates = [
        lambda d: f"What does Section {d['section']} of the {plain(d['act_title'])} provide?",
        lambda d: (f"Explain Section {d['section']} {ABBREVIATION[d['act_id']]}." if d["act_id"] in ABBREVIATION
                   else f"Explain Section {d['section']} of the {plain(d['act_title'])}."),
        lambda d: f"Under the {plain(d['act_title'])}, what is laid down in section {d['section']}?",
        lambda d: f"What is the scope of s. {d['section']} of the {plain(d['act_title'])}?",
        lambda d: (f"{ABBREVIATION[d['act_id']]} {d['section']}: what does this provision say?" if d["act_id"] in ABBREVIATION
                   else f"What does the {plain(d['act_title'])} say in Section {d['section']}?"),
    ]
    for i, d in enumerate(selection["exact_section_reference"]):
        items.append(("exact_section_reference", exact_templates[i % len(exact_templates)](d), [statute_authority(docs, d["doc_id"])]))

    for i, pair in enumerate(selection["old_new_law"][:12]):
        old, new = pair["old"], pair["new"]
        if i % 3 == 0:
            question = f"Which provision of the {plain(new['act_title'])} corresponds to Section {old['section']} of the {plain(old['act_title'])}?"
        elif i % 3 == 1:
            question = f"What was the equivalent of Section {new['section']} {ABBREVIATION[new['act_id']]} under the {plain(old['act_title'])}?"
        else:
            question = (f"Which section of the {plain(new['act_title'])} deals with {new['heading'].lower()}, "
                        f"and which provision of the {plain(old['act_title'])} did it replace?")
        items.append(("old_new_law", question, [statute_authority(docs, old["doc_id"]), statute_authority(docs, new["doc_id"])]))

    for i, seed in enumerate(selection["multiple_sections_seed"]):
        first = docs[seed["doc_id"]]
        second = next_substantive(docs, first)
        if second is None:
            continue
        if i % 2 == 0:
            question = f"How do Sections {first['section']} and {second['section']} of the {plain(first['act_title'])} operate together?"
        else:
            question = (f"Under the {plain(first['act_title'])}, how do the provisions on {first['heading'].lower()} "
                        f"and {second['heading'].lower()} relate to each other?")
        items.append(("multiple_sections", question, [statute_authority(docs, first["doc_id"]), statute_authority(docs, second["doc_id"])]))

    for case in selection["case_named"][:5]:
        title = cases[case["doc_id"]]["title"]
        year = re.search(r"(\d{4})\s*$", title)
        name = re.sub(r"\s+on\s+\d{1,2}\s+[A-Za-z]+,?\s+\d{4}\s*$", "", title)
        name = re.sub(r"\s+vs?\s*\.?\s+", " v. ", name).strip()
        question = f"What did the court decide in {name}" + (f" ({year.group(1)})?" if year else "?")
        items.append(("case_law_named", question, [case_authority(cases, case["doc_id"])]))
    return items


def authored(docs, cases):
    items, rejected = [], []
    for entry in json.loads((OUT / "authored_questions.json").read_text())["questions"]:
        try:
            authorities = []
            for spec in entry["authorities"]:
                if spec["type"] == "statute":
                    authorities.append(statute_authority(docs, spec["doc_id"], spec["evidence_phrase"]))
                elif spec["type"] == "case_principle":
                    authorities.append(principle_authority(cases, spec["source_doc_id"], spec["evidence_phrase"]))
                else:
                    authorities.append(case_authority(cases, spec["doc_id"]))
            items.append((entry["category"], entry["question"], authorities))
        except ValueError as error:
            rejected.append({"question": entry["question"], "reason": str(error)})
    return items, rejected


def build(args):
    docs, cases = load_corpus()
    selection = json.loads((OUT / "sources_sample.json").read_text())
    pilot_seeds = pilot_seed_ids()
    authored_items, rejected = authored(docs, cases)
    records = []
    for construction, group in (("templated", templated(selection, docs, cases)), ("authored", authored_items)):
        for category, question, authorities in group:
            overlap = sorted({d for a in authorities if a["equivalence"] == "exact" for d in a["doc_ids"]} & pilot_seeds)
            if overlap:
                rejected.append({"question": question, "reason": f"uses pilot seed documents {overlap}"})
                continue
            digest = hashlib.sha256(f"{category}|{question}".encode("utf-8")).hexdigest()[:10]
            records.append({"id": f"fr-{digest}", "category": category, "question": question,
                            "construction": construction, "authorities": authorities})
    with (OUT / "questions.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = {"questions": len(records), "by_category": dict(sorted(Counter(r["category"] for r in records).items())),
               "by_construction": dict(Counter(r["construction"] for r in records)), "rejected": rejected}
    (OUT / "build_report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sample")
    sub.add_parser("build")
    args = parser.parse_args()
    if args.command == "sample":
        sample(args)
    else:
        build(args)


if __name__ == "__main__":
    main()
