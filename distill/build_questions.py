"""
Stage 1 — grounded, validated question generation.

Samples seed passages from the real corpus (statute sections, judgment passages, old/new code pairs) and
asks Claude to write ONE realistic question per seed, of a given type, together with the exact words in
the passage(s) that answer it. Claude only writes the question here: answers come later from the full
IndianLawGPT pipeline (stage 2), which never sees the seed passage.

A question is accepted only if every check passes:
  1. its seed sources exist in the corpus;
  2. the generator's evidence quotes occur verbatim in every passage the category requires;
  3. an independent reviewer call confirms it is answerable from those passages, needs every required
     passage, and is not ambiguous — and its own supporting quotes are verbatim;
  4. the intended chunk(s) holding the evidence are identified in the vector store;
  5. required authorities are recorded: statute sections exactly; a judgment exactly when the question
     names the case (checked against the case title), otherwise as every judgment in the corpus stating
     the same principle (a verbatim principle phrase);
  6. insufficient_evidence labels are checked against the corpus (seed sections in full plus what the
     retriever finds): a question the corpus can answer is rejected, never labelled insufficient.
Plus: no tool/XML markup, no meta references to "the passage", no exact or near-duplicate questions.

Resumable and deterministic: seed candidates come from a per-category random stream fixed by --run; each
processed candidate is logged to question_attempts.jsonl and skipped on resume; accepted questions are
appended to questions.jsonl in candidate order even when several are processed in parallel.

Usage (from the repository root):
    .venv/bin/python distill/build_questions.py --run pilot_v2 --target 50 --workers 4 \
        --exclude-seeds data/distill/retrieval_eval/heldout_v2/questions.jsonl
"""
import argparse
import html
import json
import random
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from common import (
    SEED, append_jsonl, call_claude_tool, get_logger, jaccard, log_failure, normalized_text, now_iso,
    question_tokens, read_jsonl, run_dir, settings, short_hash,
)
from db import get_connection
from ingest_statutes import make_statute_doc_id

logger = get_logger("distill.questions")

# category -> (relative share of the dataset, instruction given to Claude)
CATEGORIES = {
    "section_identification": (10, "Describe a situation or rule set out in the passage and ask which provision governs it. Name the Act, but do NOT give the section number or repeat the heading's exact words."),
    "definition": (8, "Ask what a term defined in the passage means under that Act. Name the Act and the term."),
    "applicability": (8, "Ask whether, to whom, where or when the provision applies. Name the Act."),
    "interpretation": (10, "Ask how a specific phrase, condition or requirement in the provision should be understood. Name the Act."),
    "procedural": (8, "Ask a procedural question the passage answers: steps, time limits, the competent authority, or what must be filed or done. Name the Act."),
    "punishment": (7, "Ask what punishment or penalty the law prescribes for the conduct described in the passage. Name the Act."),
    "exception": (7, "Ask about an exception, proviso or circumstance in which the general rule in the passage does not apply. Name the Act."),
    "fact_pattern": (10, "Write a short realistic scenario (2-4 sentences, invented names) and ask how the law in the passage applies to it. Name the Act."),
    "multiple_sections": (8, "Ask one question that needs BOTH passages to answer fully. Name the Act."),
    "statute_comparison": (7, "The passages come from two different Acts on a similar subject. Ask how the two provisions compare. Name both Acts."),
    "old_new_law": (8, "Passage 1 is from an old code and Passage 2 is its counterpart in the new code. Ask which new provision corresponds to the old one (or vice versa) and how they differ. Name both codes."),
    "case_law": (7, "The passage is from a court judgment. Ask about the legal position or reasoning it sets out, phrased as a general legal question (do not name the parties). Copy into principle_phrase the exact words (6-30 words) from the passage that state that legal position."),
    "multiple_authorities": (5, "Passage 1 is a statutory provision and Passage 2 is from a judgment applying the same law. Ask one question that needs both the statute and the court's reasoning (e.g. 'how have courts applied ...'). Copy into principle_phrase the exact words (6-30 words) from the judgment passage that state the court's reasoning."),
    "insufficient_evidence": (5, "Ask a realistic question on the same subject that the passage does NOT answer - e.g. a specific figure, procedure, rule, notification or judicial position that is absent. It must sound natural, not like a trick. Leave evidence_quotes empty."),
}
CASE_SPECIFIC_INSTRUCTION = (
    "The passage is from a court judgment. Ask what THIS judgment decided or reasoned on the point the passage covers, "
    "naming the case by its parties exactly as they appear in the title. Set names_specific_case to true."
)
CASE_SPECIFIC_SHARE = 0.3
MULTI_PASSAGE = {"multiple_sections", "statute_comparison", "old_new_law", "multiple_authorities"}

QUESTION_TOOL = {
    "name": "write_question",
    "description": "Submit one grounded legal research question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question, able to stand on its own."},
            "answer_hint": {
                "type": "string",
                "description": "One sentence: what in the passages answers it (for insufficient_evidence: what is missing).",
            },
            "evidence_quotes": {
                "type": "array",
                "description": "For every passage the answer needs: exact words (at least 8) copied from that passage that answer the question.",
                "items": {
                    "type": "object",
                    "properties": {"passage": {"type": "integer"}, "quote": {"type": "string"}},
                    "required": ["passage", "quote"],
                },
            },
            "principle_phrase": {
                "type": "string",
                "description": "Judgment passages only: exact words copied from the judgment passage that state the legal principle the question relies on.",
            },
            "names_specific_case": {
                "type": "boolean",
                "description": "True only if the question names or clearly identifies this particular judgment.",
            },
        },
        "required": ["question", "answer_hint", "evidence_quotes"],
    },
}

SYSTEM = """You write questions for the training and evaluation set of an Indian legal research assistant.
Write exactly ONE question of the requested type, grounded in the passage(s) provided.
The question will later be answered by a system that searches Indian statutes and judgments. That system will NOT see these passages, so the question must stand on its own.
Rules:
- Sound like a real lawyer, law student or informed citizen in India. Never refer to "the passage", "the excerpt" or "the text above".
- Unless the type says otherwise, the passage(s) must contain what is needed to answer the question, and evidence_quotes must copy the exact words that answer it.
- Name the Act where it helps a reader know which law is meant (e.g. "under the Negotiable Instruments Act, 1881").
- The question must have one clear reading: say which law, provision or situation is meant.
- Use one sentence where possible; fact patterns may use 2-4 short sentences with invented names.
- Do not ask questions whose answer is just the section's wording repeated back."""

REVIEW_TOOL = {
    "name": "review_question",
    "description": "Report whether the draft question is valid for the passages.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answerable": {"type": "boolean"},
            "uses_every_passage": {"type": "boolean"},
            "ambiguous": {"type": "boolean"},
            "well_formed": {"type": "boolean"},
            "principle_phrase_is_legal_principle": {"type": "boolean"},
            "supporting_quotes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"passage": {"type": "integer"}, "quote": {"type": "string"}},
                    "required": ["passage", "quote"],
                },
            },
            "problem": {"type": "string"},
        },
        "required": ["answerable", "uses_every_passage", "ambiguous", "well_formed", "principle_phrase_is_legal_principle", "supporting_quotes", "problem"],
    },
}

REVIEW_SYSTEM = """You review draft questions for an Indian legal research dataset. Judge the question ONLY against the passages given; do not use outside knowledge.
- answerable: true only if the passages contain what is needed to give the specific answer the question asks for.
- uses_every_passage: true only if a complete answer needs every passage provided.
- ambiguous: true if a careful lawyer could not tell which law, provision, party or situation is meant, or if the question has reasonable readings that lead to different answers.
- well_formed: true only for a natural, focused question a lawyer, law student or informed citizen would actually ask - not convoluted or several questions in one, no false premise, and it does not give away details of the answer.
- principle_phrase_is_legal_principle: if a principle phrase is shown, true only if it states a legal rule or reasoning that other judgments could also apply - false for case-specific findings, procedural history or boilerplate (e.g. "ingredient I stands fulfilled in the present case"). If no principle phrase is shown, true.
- supporting_quotes: for each passage the answer relies on, exact words (at least 8) copied from that passage that support the answer.
- problem: one short sentence naming any defect (wrong premise, unanswerable, ambiguous, trivial), otherwise empty."""

# Second opinion for insufficient_evidence labels: can the question in fact be answered from the seed
# section or from what the IndianLawGPT retriever finds for it?
ANSWERABILITY_TOOL = {
    "name": "check_answerability",
    "description": "Report whether the passages answer the question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answerable": {"type": "boolean"},
            "supporting_quote": {
                "type": "string",
                "description": "If answerable: the exact words, copied from one passage, that give the answer. Otherwise empty.",
            },
        },
        "required": ["answerable", "supporting_quote"],
    },
}

ANSWERABILITY_SYSTEM = """You check whether a legal research question can be answered from the passages provided.
Answerable means a careful reader could give the specific answer the question asks for (a figure, time limit, rule, condition, authority, definition or judicial position) using only these passages - even if the wording differs, or the answer sits in a proviso, explanation, illustration or list.
If answerable, copy the exact words from one passage that give the answer into supporting_quote. If not, set answerable to false and leave supporting_quote empty.
Do not use outside knowledge."""

# Tool-call or XML-style tags that can leak into generated fields (e.g. "</answer_hint></invoke>").
MARKUP = re.compile(r"</?[A-Za-z_][\w:.-]*(?:\s[^<>]*)?/?>")

PRIORITY_ACTS = {
    "ipc", "bns", "crpc", "bnss", "iea", "bsa", "ni-act", "constitution-of-india", "contract-act", "companies-act",
    "consumer-protection-act", "hindu-marriage-act", "hindu-succession-act-1956", "arbitration-act",
    "specific-relief-act", "limitation-act", "sexual-harassment-women-at-workplace-prevention-prohibition-redressal",
    "pocso-act", "dowry-prohibition-act-1961", "juvenile-justice-care-protection-children-act-2015",
    "insolvency-bankruptcy-code-2016", "partnership-act", "limited-liability-partnership-act-2008", "sale-of-goods-act",
    "trade-marks-act", "copyright-act", "delhi-rent-control-act-1958", "stamp-act", "income-tax-act", "income-tax-act-2025",
    "cpc", "transfer-of-property-act", "information-technology-act", "motor-vehicles-act", "general-clauses-act",
}
CRIMINAL_ACTS = {
    "ipc", "bns", "ni-act", "pocso-act", "dowry-prohibition-act-1961", "juvenile-justice-care-protection-children-act-2015",
    "prevention-illicit-traffic-narcotic-drugs-psychotropic-substances-act", "companies-act", "copyright-act", "trade-marks-act",
    "information-technology-act",
}
CIVIL_FACT_ACTS = {"contract-act", "consumer-protection-act", "sale-of-goods-act", "specific-relief-act", "partnership-act", "transfer-of-property-act"}
PROCEDURAL_ACTS = {
    "crpc", "bnss", "cpc", "limitation-act", "arbitration-act", "consumer-protection-act", "insolvency-bankruptcy-code-2016",
    "iea", "bsa", "ni-act",
}
MAPPED_FAMILIES = [{"ipc", "bns"}, {"crpc", "bnss"}, {"iea", "bsa"}, {"income-tax-act", "income-tax-act-2025"}]
NI_ACT_CORE = ["118", "138", "139", "140", "141", "142", "143", "143A", "145", "146", "147", "148"]
GENERIC_PARTY_WORDS = {
    "state", "bank", "limited", "private", "company", "others", "another", "india", "union", "through", "delhi",
    "government", "finance", "financial", "services", "securities", "industries", "enterprises", "traders", "trading",
    "court", "cases", "case", "appeal", "criminal", "complainant", "accused", "respondent", "petitioner",
}

GENERIC_HEADING = re.compile(
    r"short title|definition|interpretation|power to make rules|\brules\b|regulations|repeal|saving|commencement|"
    r"\bextent\b|protection of action|good faith|remove difficult|delegation|laid before|amendment of|transitional",
    re.IGNORECASE,
)
OMITTED = re.compile(r"^\W*(?:omitted|repealed)", re.IGNORECASE)
APPLIES = re.compile(r"\bappl(?:y|ies|icable)\b", re.IGNORECASE)
META_REFERENCE = re.compile(r"\b(?:the|this|above|given|provided|following)\s+(?:passage|excerpt|extract|text)s?\b", re.IGNORECASE)
MIN_QUOTE_WORDS = 5
TRANSIENT_FAILURES = {"claude_error", "validation_error"}
MAX_TRANSIENT_RETRIES = 4


def punishes(doc) -> bool:
    return "punish" in doc["heading"].lower() or "shall be punished" in doc["text"]


def section_key(number) -> tuple:
    match = re.match(r"(\d+)\s*([A-Za-z]*)", str(number or ""))
    return (int(match.group(1)), match.group(2).upper()) if match else (10 ** 9, str(number))


def same_family(a: str, b: str) -> bool:
    return any({a, b} <= family for family in MAPPED_FAMILIES)


def well_formed_case_title(title: str) -> bool:
    return bool(re.search(r"\bvs?\.?\s+\w", title or "")) and "..." not in (title or "") and not re.match(
        r"^(CT CASES|CC|Crl|CR)\b", title or "", re.IGNORECASE)


class Corpus:
    def __init__(self):
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT doc_id, full_text, metadata_json FROM documents WHERE source_type = 'statute' ORDER BY doc_id"
            ).fetchall()
            judgments = conn.execute(
                "SELECT doc_id, title, court, date, full_text FROM documents WHERE source_type = 'case_law' ORDER BY doc_id"
            ).fetchall()
        finally:
            conn.close()

        self.statutes = {}
        self.by_act = defaultdict(list)
        for row in rows:
            meta = json.loads(row["metadata_json"] or "{}")
            doc = {
                "doc_id": row["doc_id"], "act_id": meta.get("act_id"), "act_title": meta.get("act_title"),
                "section": meta.get("section_number"), "heading": meta.get("section_heading") or "",
                "text": html.unescape(row["full_text"] or "").strip(), "corresponds_to": meta.get("corresponds_to") or [],
            }
            self.statutes[doc["doc_id"]] = doc
            self.by_act[doc["act_id"]].append(doc)
        for docs in self.by_act.values():
            docs.sort(key=lambda d: section_key(d["section"]))

        self.substantive = [
            d for d in self.statutes.values()
            if 250 <= len(d["text"]) <= 6000 and not OMITTED.match(d["text"]) and not GENERIC_HEADING.search(d["heading"])
        ]
        self.substantive_ids = {d["doc_id"] for d in self.substantive}
        self.priority_substantive = [d for d in self.substantive if d["act_id"] in PRIORITY_ACTS]
        self.definitions = [
            d for d in self.statutes.values() if "definition" in d["heading"].lower() and 250 <= len(d["text"]) <= 12000
        ]
        self.priority_definitions = [d for d in self.definitions if d["act_id"] in PRIORITY_ACTS]
        self.judgments = [
            {**dict(r), "full_text": html.unescape(r["full_text"] or "")} for r in judgments if len(r["full_text"] or "") > 1200
        ]
        self.judgments_by_id = {j["doc_id"]: j for j in self.judgments}
        self.well_formed_judgments = [j for j in self.judgments if well_formed_case_title(j["title"])]
        self._judgment_norms = {r["doc_id"]: normalized_text(html.unescape(r["full_text"] or "")) for r in judgments}

        headings = defaultdict(list)
        for doc in self.substantive:
            key = normalized_text(doc["heading"])
            if len(key) > 8:
                headings[key].append(doc)
        self.shared_headings = [docs for docs in headings.values() if len({d["act_id"] for d in docs}) >= 2]

        self.mapped_pairs = []
        seen_pairs = set()
        for doc in self.statutes.values():
            for link in doc["corresponds_to"]:
                if not isinstance(link, dict) or link.get("relation") in (None, "none", "official-none"):
                    continue
                if not link.get("act") or not link.get("section"):
                    continue
                target = self.statutes.get(make_statute_doc_id(link["act"], link["section"]))
                if not target or len(target["text"]) < 120 or len(doc["text"]) < 120:
                    continue
                old, new = (doc, target) if link.get("direction") == "successor" else (target, doc)
                if (old["doc_id"], new["doc_id"]) not in seen_pairs:
                    seen_pairs.add((old["doc_id"], new["doc_id"]))
                    self.mapped_pairs.append((old, new))

        logger.info(
            "Corpus loaded: %d statute sections (%d substantive), %d definitions, %d judgments (%d with party titles), %d shared headings, %d old/new pairs",
            len(self.statutes), len(self.substantive), len(self.definitions), len(self.judgments),
            len(self.well_formed_judgments), len(self.shared_headings), len(self.mapped_pairs),
        )

    def pick_section(self, rng, predicate=lambda d: True, acts=None, acts_share=0.7):
        if acts and rng.random() < acts_share:
            pool = [d for d in self.substantive if d["act_id"] in acts and predicate(d)]
        elif rng.random() < 0.7:
            pool = [d for d in self.priority_substantive if predicate(d)]
        else:
            pool = [d for d in self.substantive if predicate(d)]
        if not pool:
            pool = [d for d in self.substantive if predicate(d)] or self.substantive
        return rng.choice(pool)

    def next_substantive(self, doc):
        docs = self.by_act[doc["act_id"]]
        index = next((i for i, d in enumerate(docs) if d["doc_id"] == doc["doc_id"]), None)
        if index is None:
            return None
        return next((d for d in docs[index + 1:index + 4] if d["doc_id"] in self.substantive_ids), None)

    def comparison_pair(self, rng):
        # Favour comparisons involving at least one widely used Act over pairs of obscure ones.
        if not hasattr(self, "_priority_shared_headings"):
            self._priority_shared_headings = [
                docs for docs in self.shared_headings if any(d["act_id"] in PRIORITY_ACTS for d in docs)
            ]
        for _ in range(20):
            pool = self._priority_shared_headings if self._priority_shared_headings and rng.random() < 0.7 else self.shared_headings
            docs = rng.choice(pool)
            first = rng.choice(docs)
            others = [d for d in docs if d["act_id"] != first["act_id"] and not same_family(first["act_id"], d["act_id"])]
            if others:
                return first, rng.choice(others)
        return None

    def ni_act_core(self, rng):
        candidates = [self.statutes.get(make_statute_doc_id("ni-act", number)) for number in NI_ACT_CORE]
        candidates = [d for d in candidates if d]
        return rng.choice(candidates) if candidates else None

    def judgments_containing(self, phrase):
        """Every judgment in the corpus whose text contains `phrase` (case- and punctuation-insensitive)."""
        target = normalized_text(phrase)
        return sorted(doc_id for doc_id, text in self._judgment_norms.items() if target and target in text)

    def full_text(self, doc_id):
        if doc_id in self.statutes:
            return self.statutes[doc_id]["text"]
        judgment = self.judgments_by_id.get(doc_id)
        return judgment["full_text"] if judgment else ""


def statute_passage(doc):
    label = f"{doc['act_title']} - Section {doc['section']}"
    if doc["heading"]:
        label += f" ({doc['heading']})"
    return {"doc_id": doc["doc_id"], "label": label, "section": doc["section"], "text": doc["text"][:2500], "kind": "statute"}


def judgment_passage(judgment, rng, size=1800):
    text = judgment["full_text"]
    start = 0
    if len(text) > size:
        low = int(len(text) * 0.15)
        start = rng.randint(low, max(low, int(len(text) * 0.85) - size))
        boundary = text.find(". ", start)
        if boundary != -1 and boundary - start < 300:
            start = boundary + 2
    end = min(len(text), start + size)
    stop = text.rfind(". ", start, end)
    if stop > start + size // 2:
        end = stop + 1
    label = f"{judgment['title']} ({judgment['court'] or 'court not recorded'}, {judgment['date'] or 'date not recorded'})"
    return {"doc_id": judgment["doc_id"], "label": label, "section": None, "text": text[start:end].strip(), "kind": "case_law",
            "title": judgment["title"]}


def judgment_passage_around(judgment, position, size=1800):
    """A judgment passage of about `size` characters centred on `position`, cut at sentence boundaries."""
    text = judgment["full_text"]
    start = max(0, position - size // 2)
    boundary = text.find(". ", start)
    if boundary != -1 and boundary - start < 300 and boundary < position:
        start = boundary + 2
    end = min(len(text), start + size)
    stop = text.rfind(". ", max(position, start + size // 2), end)
    if stop != -1:
        end = stop + 1
    label = f"{judgment['title']} ({judgment['court'] or 'court not recorded'}, {judgment['date'] or 'date not recorded'})"
    return {"doc_id": judgment["doc_id"], "label": label, "section": None, "text": text[start:end].strip(), "kind": "case_law",
            "title": judgment["title"]}


def seed_for(category, corpus, rng):
    case_law_type = None
    if category == "definition":
        pool = corpus.priority_definitions if corpus.priority_definitions and rng.random() < 0.7 else corpus.definitions
        passages = [statute_passage(rng.choice(pool))]
    elif category == "punishment":
        passages = [statute_passage(corpus.pick_section(rng, punishes, acts=CRIMINAL_ACTS))]
    elif category == "fact_pattern":
        predicate = lambda d: punishes(d) or "liable" in d["text"]  # noqa: E731
        passages = [statute_passage(corpus.pick_section(rng, predicate, acts=CRIMINAL_ACTS | CIVIL_FACT_ACTS, acts_share=0.8))]
    elif category == "procedural":
        passages = [statute_passage(corpus.pick_section(rng, acts=PROCEDURAL_ACTS, acts_share=0.85))]
    elif category == "exception":
        passages = [statute_passage(corpus.pick_section(rng, lambda d: "Provided that" in d["text"] or "Exception" in d["text"]))]
    elif category == "applicability":
        passages = [statute_passage(corpus.pick_section(rng, lambda d: APPLIES.search(d["text"]) is not None))]
    elif category == "multiple_sections":
        first = corpus.pick_section(rng)
        second = corpus.next_substantive(first)
        if second is None:
            return None
        passages = [statute_passage(first), statute_passage(second)]
    elif category == "statute_comparison":
        pair = corpus.comparison_pair(rng)
        if pair is None:
            return None
        passages = [statute_passage(doc) for doc in pair]
    elif category == "old_new_law":
        if not corpus.mapped_pairs:
            return None
        # Pick the code family first (IPC/BNS, CrPC/BNSS, IEA/BSA, Income-tax 1961/2025), then a pair, so
        # the family with the most stored correspondences does not dominate.
        families = sorted({old["act_id"] for old, _ in corpus.mapped_pairs})
        family = rng.choice(families)
        old, new = rng.choice([pair for pair in corpus.mapped_pairs if pair[0]["act_id"] == family])
        passages = [statute_passage(old), statute_passage(new)]
    elif category == "case_law":
        if corpus.well_formed_judgments and rng.random() < CASE_SPECIFIC_SHARE:
            case_law_type = "specific_judgment"
            passages = [judgment_passage(rng.choice(corpus.well_formed_judgments), rng)]
        else:
            case_law_type = "legal_principle"
            passages = [judgment_passage(rng.choice(corpus.judgments), rng)]
    elif category == "multiple_authorities":
        statute = corpus.ni_act_core(rng)
        if statute is None or not corpus.judgments:
            return None
        case_law_type = "legal_principle"
        # The judgment passage must discuss the chosen section, or no question can need both authorities.
        mention = re.compile(rf"\b(?:section|sec\.?|s\.|u/s\.?)\s*{re.escape(str(statute['section']))}\b", re.IGNORECASE)
        candidates = [(j, m.start()) for j in corpus.judgments for m in [mention.search(j["full_text"], int(len(j["full_text"]) * 0.15))] if m]
        if not candidates:
            return None
        judgment, position = rng.choice(candidates)
        passages = [statute_passage(statute), judgment_passage_around(judgment, position)]
    else:  # section_identification, interpretation, insufficient_evidence
        passages = [statute_passage(corpus.pick_section(rng))]
    return {"passages": passages, "doc_ids": [p["doc_id"] for p in passages], "case_law_type": case_law_type}


def allocate(target: int, shares=None) -> dict:
    """Split `target` across categories by share, largest remainder first."""
    shares = shares or {category: share for category, (share, _) in CATEGORIES.items()}
    total = sum(shares.values())
    exact = {category: target * share / total for category, share in shares.items()}
    counts = {category: int(value) for category, value in exact.items()}
    remaining = target - sum(counts.values())
    for category in sorted(exact, key=lambda c: exact[c] - counts[c], reverse=True)[:remaining]:
        counts[category] += 1
    return counts


def strip_markup(text):
    return " ".join(MARKUP.sub(" ", str(text or "")).split())


def party_names(title):
    """Distinctive party-name words from a judgment title such as 'Rachit Chawla vs Gurdeep Singh Bhatia on 21 January, 2025'."""
    name = re.sub(r"\s+on\s+\d{1,2}\s+[A-Za-z]+,?\s+\d{4}\s*$", "", title or "")
    sides = re.split(r"\s+vs?\.?\s+", name, maxsplit=1, flags=re.IGNORECASE)
    return [
        {w for w in re.findall(r"[a-z]+", side.lower()) if len(w) >= 4 and w not in GENERIC_PARTY_WORDS}
        for side in sides
    ]


def names_case(question, title):
    """True when the question names the parties of this judgment (a word from each side, or two words)."""
    words = set(re.findall(r"[a-z]+", question.lower()))
    sides = [side & words for side in party_names(title)]
    return (len(sides) == 2 and all(sides)) or sum(len(side) for side in sides) >= 2


def verbatim_in(quote, text, min_words=MIN_QUOTE_WORDS):
    target = normalized_text(quote)
    return len(target.split()) >= min_words and target in normalized_text(text)


@lru_cache(maxsize=4096)
def chunk_texts(doc_id):
    from vector_store import get_vector_store
    got = get_vector_store().collection.get(where={"doc_id": doc_id}, include=["documents", "metadatas"])
    return tuple((meta.get("chunk_id"), normalized_text(text)) for meta, text in zip(got["metadatas"], got["documents"]))


def chunks_with(doc_id, quotes):
    found = []
    for quote in quotes:
        target = normalized_text(quote)
        hits = [cid for cid, text in chunk_texts(doc_id) if target and target in text]
        if not hits:  # quote crosses a chunk boundary: accept chunks holding its opening words
            opening = " ".join(target.split()[:8])
            hits = [cid for cid, text in chunk_texts(doc_id) if opening and opening in text]
        found.extend(h for h in hits if h not in found)
    return found


def required_passages(category, seed):
    return list(range(1, len(seed["passages"]) + 1)) if category in MULTI_PASSAGE else [1]


def quotes_by_passage(quotes, seed, corpus):
    """Verbatim quotes per 1-based passage number (checked against the source's full text)."""
    grouped = defaultdict(list)
    for item in quotes or []:
        try:
            number = int(item.get("passage"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not 1 <= number <= len(seed["passages"]):
            continue
        quote = strip_markup(item.get("quote"))
        passage = seed["passages"][number - 1]
        if verbatim_in(quote, corpus.full_text(passage["doc_id"])):
            grouped[number].append(quote)
    return grouped


def build_authorities(category, seed, question, proposal, generator_quotes, corpus):
    """One authority per required passage (see module docstring). Returns (authorities, problem)."""
    authorities = []
    for number in required_passages(category, seed):
        passage = seed["passages"][number - 1]
        quotes = generator_quotes.get(number, [])
        if passage["kind"] == "statute":
            authorities.append({"kind": "statute", "doc_ids": [passage["doc_id"]], "equivalence": "exact",
                                "source_doc_id": passage["doc_id"], "evidence_quotes": quotes,
                                "intended_chunk_ids": chunks_with(passage["doc_id"], quotes)})
            continue
        named = names_case(question, passage["title"])
        if seed.get("case_law_type") == "specific_judgment" or proposal.get("names_specific_case"):
            if not named:
                return None, "specific_case_question_does_not_name_parties"
            authorities.append({"kind": "case_law", "doc_ids": [passage["doc_id"]], "equivalence": "exact",
                                "case_law_type": "specific_judgment", "source_doc_id": passage["doc_id"],
                                "evidence_quotes": quotes, "intended_chunk_ids": chunks_with(passage["doc_id"], quotes)})
            continue
        if named:
            return None, "principle_question_names_the_case"
        phrase = strip_markup(proposal.get("principle_phrase"))
        words = normalized_text(phrase).split()
        if not 6 <= len(words) <= 40 or not verbatim_in(phrase, passage["text"], min_words=6):
            return None, "principle_phrase_not_verbatim"
        equivalents = corpus.judgments_containing(phrase)
        if passage["doc_id"] not in equivalents:
            return None, "principle_phrase_not_in_seed_judgment"
        authorities.append({
            "kind": "case_law", "doc_ids": equivalents, "equivalence": "principle", "case_law_type": "legal_principle",
            "principle_phrase": phrase, "source_doc_id": passage["doc_id"], "evidence_quotes": quotes,
            "intended_chunk_ids": [cid for doc_id in equivalents for cid in chunks_with(doc_id, [phrase])],
        })
    for authority in authorities:
        if not authority["intended_chunk_ids"]:
            return None, "intended_chunk_not_identified"
    return authorities, None


def review_question(question, category, seed, corpus, principle_phrases=(), ask=call_claude_tool):
    """Independent reviewer call: answerable, uses every required passage, unambiguous, well formed, a
    genuine legal principle where one is relied on, and verbatim support."""
    passages = [(p, corpus.full_text(p["doc_id"])[:6000] if p["kind"] == "statute" else p["text"]) for p in seed["passages"]]
    principle = "".join(f"\nPrinciple phrase relied on: \"{phrase}\"" for phrase in principle_phrases)
    prompt = f"Question type: {category}\nDraft question: {question}{principle}\n\n" + "\n\n".join(
        f"[Passage {i}] {p['label']}\n{text}" for i, (p, text) in enumerate(passages, 1)
    )
    review = ask(REVIEW_TOOL, REVIEW_SYSTEM, prompt, max_tokens=800)
    verified = quotes_by_passage(review.get("supporting_quotes"), seed, corpus)
    needed = required_passages(category, seed)
    problems = []
    if not review.get("answerable"):
        problems.append("reviewer_not_answerable")
    if review.get("ambiguous"):
        problems.append("reviewer_ambiguous")
    if category in MULTI_PASSAGE and not review.get("uses_every_passage"):
        problems.append("reviewer_does_not_need_every_passage")
    if not review.get("well_formed"):
        problems.append("reviewer_not_well_formed")
    if principle_phrases and not review.get("principle_phrase_is_legal_principle"):
        problems.append("reviewer_principle_not_a_legal_principle")
    if any(number not in verified for number in needed):
        problems.append("reviewer_quotes_not_verbatim")
    return {
        "accepted": not problems, "problems": problems, "answerable": bool(review.get("answerable")),
        "ambiguous": bool(review.get("ambiguous")), "uses_every_passage": bool(review.get("uses_every_passage")),
        "well_formed": bool(review.get("well_formed")),
        "principle_phrase_is_legal_principle": bool(review.get("principle_phrase_is_legal_principle")) if principle_phrases else None,
        "reviewer_problem": strip_markup(review.get("problem")), "verified_quotes": {str(k): v for k, v in verified.items()},
        "reviewer_model": settings.anthropic_model,
    }


def verify_insufficient(question, seed, corpus, ask=call_claude_tool, retrieve=None):
    """Checks an insufficient_evidence label against the corpus before the question is accepted: the
    seed sections in full plus the passages production retrieval returns for the question. The label
    survives only if the checker finds no answer; a claimed answer must quote a passage verbatim."""
    if retrieve is None:
        from search import hybrid_search
        retrieve = lambda q: hybrid_search(q, top_k=8)  # noqa: E731
    passages = []
    for passage in seed["passages"]:
        full_text = (corpus.statutes.get(passage["doc_id"]) or {}).get("text") or passage["text"]
        passages.append((passage["doc_id"], passage["label"], full_text[:6000]))
    for hit in retrieve(question):
        if hit["doc_id"] not in {doc_id for doc_id, _, _ in passages}:
            passages.append((hit["doc_id"], hit.get("title") or hit["doc_id"], hit.get("text") or ""))

    prompt = f"Question: {question}\n\n" + "\n\n".join(
        f"[Passage {i}] {label}\n{text}" for i, (_, label, text) in enumerate(passages, 1)
    )
    proposal = ask(ANSWERABILITY_TOOL, ANSWERABILITY_SYSTEM, prompt, max_tokens=500)
    answerable = bool(proposal.get("answerable"))
    quote = strip_markup(proposal.get("supporting_quote"))
    quote_norm = normalized_text(quote)
    quote_found = len(quote_norm.split()) >= 3 and any(quote_norm in normalized_text(text) for _, _, text in passages)
    verdict = "insufficient" if not answerable else "answerable" if quote_found else "answerable_unverified_quote"
    return {
        "verdict": verdict, "classification": "TRUE_INSUFFICIENT" if verdict == "insufficient" else "ANSWERABLE_FROM_CORPUS",
        "answerable_claimed": answerable, "supporting_quote": quote,
        "quote_found_in_passages": quote_found, "checked_doc_ids": [doc_id for doc_id, _, _ in passages],
        "checker_model": settings.anthropic_model, "checked_at": now_iso(),
    }


def basic_problem(question, raw_question, category, seed):
    if MARKUP.search(raw_question):
        return "markup_in_question"
    if not 20 <= len(question) <= {"fact_pattern": 700, "multiple_authorities": 600}.get(category, 450):
        return "bad_length"
    if META_REFERENCE.search(question):
        return "refers_to_passage"
    if category == "section_identification":
        for passage in seed["passages"]:
            number = passage.get("section")
            if number and re.search(rf"\b(?:section|sec\.?|s\.|article)\s*{re.escape(str(number))}\b", question, re.IGNORECASE):
                return "names_seed_section"
    return None


def build_prompt(category, seed):
    instruction = CASE_SPECIFIC_INSTRUCTION if seed.get("case_law_type") == "specific_judgment" and category == "case_law" else CATEGORIES[category][1]
    blocks = "\n\n".join(f"[Passage {i}] {p['label']}\n{p['text']}" for i, p in enumerate(seed["passages"], 1))
    return f"Question type: {category}\nInstruction: {instruction}\n\n{blocks}"


def process_candidate(category, seed, corpus, ask=call_claude_tool, retrieve=None):
    """Generates and validates one question. Returns {"accepted": bool, "reason": str, "record": dict|None, ...}.
    `ask` and `retrieve` can be replaced for offline tests."""
    try:
        proposal = ask(QUESTION_TOOL, SYSTEM, build_prompt(category, seed))
    except Exception as error:
        return {"accepted": False, "reason": "claude_error", "error": str(error)}
    raw_question = str(proposal.get("question", ""))
    question = strip_markup(raw_question)
    problem = basic_problem(question, raw_question, category, seed)
    if problem:
        return {"accepted": False, "reason": problem, "question": question}

    record = {
        "category": category, "question": question,
        "expected": "insufficient" if category == "insufficient_evidence" else "answerable",
        "seed": {
            "doc_ids": seed["doc_ids"], "labels": [p["label"] for p in seed["passages"]],
            "answer_hint": strip_markup(proposal.get("answer_hint")),
        },
    }
    try:
        if category == "insufficient_evidence":
            check = verify_insufficient(question, seed, corpus, ask=ask, retrieve=retrieve)
            if check["verdict"] != "insufficient":
                return {"accepted": False, "reason": f"insufficient_label_rejected:{check['verdict']}", "question": question, "check": check}
            record["insufficiency_check"] = check
            record["seed"]["authorities"] = []
        else:
            generator_quotes = quotes_by_passage(proposal.get("evidence_quotes"), seed, corpus)
            if any(number not in generator_quotes for number in required_passages(category, seed)):
                return {"accepted": False, "reason": "evidence_quotes_not_verbatim", "question": question}
            authorities, problem = build_authorities(category, seed, question, proposal, generator_quotes, corpus)
            if problem:
                return {"accepted": False, "reason": problem, "question": question}
            phrases = [a["principle_phrase"] for a in authorities if a.get("principle_phrase")]
            review = review_question(question, category, seed, corpus, principle_phrases=phrases, ask=ask)
            if not review["accepted"]:
                return {"accepted": False, "reason": ",".join(review["problems"]), "question": question, "review": review}
            record["seed"]["authorities"] = authorities
            record["validation"] = review
            if seed.get("case_law_type") or any(a["kind"] == "case_law" for a in authorities):
                record["case_law_type"] = next((a["case_law_type"] for a in authorities if a["kind"] == "case_law"), seed.get("case_law_type"))
    except Exception as error:
        return {"accepted": False, "reason": "validation_error", "error": str(error), "question": question}
    return {"accepted": True, "reason": "accepted", "record": record}


def seed_documents_in(paths):
    excluded = set()
    for path in paths or []:
        for item in read_jsonl(Path(path)):
            excluded.update((item.get("seed") or {}).get("doc_ids") or [])
            for authority in (item.get("seed") or {}).get("authorities") or item.get("authorities") or []:
                if authority.get("equivalence", "exact") == "exact":
                    excluded.update(authority.get("doc_ids") or [])
    return excluded


def main():
    parser = argparse.ArgumentParser(description="Generate grounded, validated legal questions for the teacher dataset.")
    parser.add_argument("--run", required=True, help="Run name, e.g. 'pilot_v2' -> data/distill/pilot_v2/")
    parser.add_argument("--target", type=int, required=True, help="Total number of questions wanted in this run.")
    parser.add_argument("--workers", type=int, default=4, help="Candidates processed in parallel.")
    parser.add_argument("--shares", default=None, help="Override category shares, e.g. 'old_new_law=20,case_law=15'.")
    parser.add_argument("--exclude-seeds", nargs="*", default=[], help="Question files whose seed documents must not be reused.")
    args = parser.parse_args()

    run = run_dir(args.run)
    path = run / "questions.jsonl"
    attempts_path = run / "question_attempts.jsonl"
    existing = read_jsonl(path)
    counts = Counter(q["category"] for q in existing)
    tried = {(a["category"], a["candidate"]) for a in read_jsonl(attempts_path)}
    seen_norm = {normalized_text(q["question"]) for q in existing}
    seen_tokens = [question_tokens(q["question"]) for q in existing]
    used_seed_docs = {(q["category"], tuple(q["seed"]["doc_ids"])) for q in existing}
    excluded_docs = seed_documents_in(args.exclude_seeds)
    shares = None
    if args.shares:
        shares = {name: float(value) for name, value in (pair.split("=") for pair in args.shares.split(","))}
        unknown = set(shares) - set(CATEGORIES)
        if unknown:
            raise SystemExit(f"Unknown categories in --shares: {sorted(unknown)}")
    targets = {c: n for c, n in allocate(args.target, shares).items() if n}

    if all(counts[c] >= n for c, n in targets.items()):
        logger.info("All %d questions already generated for run '%s'.", args.target, args.run)
        return

    corpus = Corpus()
    logger.info("Excluding %d seed documents used by evaluation/other runs", len(excluded_docs))
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for category, target in targets.items():
            rng = random.Random(f"{SEED}:{args.run}:{category}")
            candidate_index = 0
            retry_queue, retries = [], Counter()
            while counts[category] < target and (candidate_index < target * 8 + 8 or retry_queue):
                batch = retry_queue[: args.workers]
                retry_queue = retry_queue[args.workers:]
                while len(batch) < args.workers and candidate_index < target * 8 + 8:
                    seed = seed_for(category, corpus, rng)
                    index = candidate_index
                    candidate_index += 1
                    if seed is None or (category, index) in tried:
                        continue
                    if set(seed["doc_ids"]) & excluded_docs or (category, tuple(seed["doc_ids"])) in used_seed_docs:
                        continue
                    batch.append((index, seed))
                results = list(pool.map(lambda item: process_candidate(category, item[1], corpus), batch))
                transient = 0
                for (index, seed), outcome in zip(batch, results):
                    if counts[category] >= target:
                        break
                    if outcome["reason"] in TRANSIENT_FAILURES:
                        # API/network failures are not a verdict on the candidate: retry it later, never mark it tried.
                        transient += 1
                        retries[index] += 1
                        log_failure(run, "questions", outcome["reason"], category=category, seed=seed["doc_ids"],
                                    attempt=retries[index], error=outcome.get("error"))
                        if retries[index] <= MAX_TRANSIENT_RETRIES:
                            retry_queue.append((index, seed))
                        continue
                    attempt = {"category": category, "candidate": index, "seed": seed["doc_ids"], "reason": outcome["reason"],
                               "question": outcome.get("question") or (outcome.get("record") or {}).get("question"), "at": now_iso()}
                    if outcome["accepted"]:
                        record = outcome["record"]
                        tokens = question_tokens(record["question"])
                        if (category, tuple(seed["doc_ids"])) in used_seed_docs:
                            # Two candidates in one parallel batch can draw the same seed.
                            attempt["reason"] = "duplicate_seed"
                        elif normalized_text(record["question"]) in seen_norm:
                            attempt["reason"] = "duplicate_question"
                        elif any(jaccard(tokens, other) >= 0.7 for other in seen_tokens):
                            attempt["reason"] = "near_duplicate_question"
                        else:
                            record = {
                                "id": f"q-{short_hash(category, record['question'])}", **record,
                                "generator": {"model": settings.anthropic_model, "run": args.run, "candidate": index, "created_at": now_iso()},
                            }
                            append_jsonl(path, record)
                            counts[category] += 1
                            seen_norm.add(normalized_text(record["question"]))
                            seen_tokens.append(tokens)
                            used_seed_docs.add((category, tuple(seed["doc_ids"])))
                            logger.info("[%s %d/%d] %s", category, counts[category], target, record["question"][:110])
                    if attempt["reason"] != "accepted":
                        log_failure(run, "questions", attempt["reason"], category=category, seed=seed["doc_ids"],
                                    question=attempt["question"], detail={k: outcome.get(k) for k in ("error", "check", "review") if outcome.get(k)})
                    append_jsonl(attempts_path, attempt)
                    tried.add((category, index))
                if transient:
                    time.sleep(min(60, 10 * transient))
            if counts[category] < target:
                logger.warning("Category %s reached only %d/%d questions (see failures.jsonl)", category, counts[category], target)

    total = sum(counts.values())
    logger.info("Questions in run '%s': %d / %d target — %s", args.run, total, args.target, dict(counts))


if __name__ == "__main__":
    main()
