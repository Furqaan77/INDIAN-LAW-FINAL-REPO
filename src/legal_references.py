"""
Explicit legal-reference lookup, old/new code mapping expansion and retrieval planning.

Finds references such as "Section 140 of the Negotiable Instruments Act, 1881", "Section 362 IPC",
"IPC 420", "s. 65B of the Evidence Act" or "Sections 10 and 11 of the Indian Evidence Act" in a query
and resolves them to statute doc_ids that exist in the SQLite corpus.

Act names come from the corpus itself (every Act title, with and without its year) plus the
abbreviations the frontend's section-reference parser already accepts (frontend/src/lib/modes.ts) and
the "NI Act" short name it displays (frontend/src/lib/format.ts). Old/new counterparts come only from
each section's stored `corresponds_to` metadata — nothing here encodes legal content.

plan_retrieval() turns those findings into evidence requirements for search.py:
  * explicit_reference  — a section the query names unambiguously;
  * mapped_counterpart  — the stored old/new counterpart of a required section, when the query also
                          names the counterpart's Act ("Which BNS provision corresponds to Section 362 IPC?");
  * case_law_authority  — the query asks how courts have treated a point, so at least one judgment is needed.
It also records the Act a query is about when it names exactly one Act and cites none of its sections
(for Act-scoped search), and the query with reference text removed (for per-authority sub-queries).
Deterministic, no model calls.
"""
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from db import get_connection, get_documents_brief
from ingest_statutes import make_statute_doc_id
from logging_config import get_logger

logger = get_logger("legal_references")

# Mirrors ACT_ALIASES in frontend/src/lib/modes.ts, plus the "NI Act" short name from format.ts.
PROJECT_ALIASES: List[Tuple[str, str]] = [
    ("bharatiya nagarik suraksha sanhita", "bnss"),
    ("bharatiya sakshya adhiniyam", "bsa"),
    ("bharatiya nyaya sanhita", "bns"),
    ("code of criminal procedure", "crpc"),
    ("indian evidence act", "iea"),
    ("indian penal code", "ipc"),
    ("evidence act", "iea"),
    ("penal code", "ipc"),
    ("cr p c", "crpc"),
    ("crpc", "crpc"),
    ("bnss", "bnss"),
    ("bns", "bns"),
    ("bsa", "bsa"),
    ("iea", "iea"),
    ("ipc", "ipc"),
    ("n i act", "ni-act"),
    ("ni act", "ni-act"),
]
# Correspondence entries that record the absence of a counterpart rather than a counterpart.
NON_MAPPING_RELATIONS = {"none", "official-none"}

# Wording that asks for judicial authority rather than (only) statutory text.
JUDICIAL_CUE = re.compile(
    r"\b(?:courts?\s+(?:have|has|had)?\s*(?:held|treated|interpreted|applied|explained|described|characteri[sz]ed|dealt|viewed|construed|ruled)"
    r"|held\s+that|judgments?|judicial(?:ly)?|precedents?|case[\s-]law|rulings?|ratio\s+decidendi"
    r"|supreme\s+court|high\s+courts?|apex\s+court)\b",
    re.IGNORECASE,
)

_SECTION_NUMBER = r"\d{1,4}[a-z]{0,3}"
_SUBDIVISIONS = r"(?:\s*\(\s*[a-z0-9]{1,4}\s*\))*"
_SECTION_GROUP = re.compile(
    r"(?<![a-z0-9])(?:sections?|secs?|ss|s|u\s*/\s*s|articles?|art)\s*\.?\s*"
    rf"(?P<first>{_SECTION_NUMBER})(?![a-z0-9]){_SUBDIVISIONS}"
    rf"(?P<rest>(?:\s*(?:,|&|\band\b|\bor\b)\s*(?:(?:sections?|s)\s*\.?\s*)?{_SECTION_NUMBER}(?![a-z0-9]){_SUBDIVISIONS})*)"
)
_NUMBER_IN_REST = re.compile(rf"(?<![a-z0-9(])({_SECTION_NUMBER})(?![a-z0-9)])")
_BARE_AFTER_ACT = re.compile(rf"^\s*,?\s*(?:(?:section|sec|s)\s*\.?\s*)?({_SECTION_NUMBER})(?![a-z0-9])")
# Allows a bracketed heading between the number and the Act: "Section 362 (Abduction) of the IPC".
_GAP_BEFORE_ACT = re.compile(r"^[\s,]*(?:\([^()]{0,80}\)[\s,]*)?(?:(?:of|under|in)\s+)?(?:the\s+)?$")
_GAP_AFTER_ACT = re.compile(r"^[\s,]*$")
_CHAIN_GAP = re.compile(r"^[\s,]*(?:read\s+with|r\s*/\s*w|and|or|along\s+with|with)?[\s,]*$")
_SAME_ACT = re.compile(r"^[\s,]*(?:of|under)\s+the\s+(?:same|said)\s+(?:act|code|sanhita|adhiniyam)\b")
# A four-digit year directly after an Act name ("... Act, 2025") that is not part of the matched name.
_TRAILING_YEAR = re.compile(r"^[\s,]*(\d{4})(?![0-9])")


@dataclass(frozen=True)
class LegalReference:
    doc_id: str
    act_id: str
    section: str
    matched_text: str
    ambiguous: bool = False  # the Act name fits more than one Act (e.g. "the Income-tax Act" with no year)


@dataclass(frozen=True)
class MappedProvision:
    doc_id: str
    act_id: str
    from_doc_id: str
    direction: Optional[str]
    relation: Optional[str]
    score: Optional[float]


@dataclass(frozen=True)
class Requirement:
    doc_id: Optional[str]  # None for case_law_authority: any suitable judgment satisfies it
    reason: str
    source_text: str = ""


@dataclass
class RetrievalPlan:
    references: List[LegalReference] = field(default_factory=list)
    mapped: List[MappedProvision] = field(default_factory=list)
    requirements: List[Requirement] = field(default_factory=list)
    act_scope: List[str] = field(default_factory=list)
    needs_case_law: bool = False
    residual_query: str = ""

    def as_dict(self) -> Dict:
        return {
            "references": [{"doc_id": r.doc_id, "matched_text": r.matched_text, "ambiguous": r.ambiguous} for r in self.references],
            "mapped": [{"doc_id": m.doc_id, "from": m.from_doc_id, "relation": m.relation, "score": m.score} for m in self.mapped],
            "requirements": [{"doc_id": q.doc_id, "reason": q.reason, "source_text": q.source_text} for q in self.requirements],
            "act_scope": list(self.act_scope),
            "needs_case_law": self.needs_case_law,
            "residual_query": self.residual_query,
        }


def _normalize(text: str) -> str:
    """Lower-cases and blanks punctuation without changing length, so offsets stay aligned with the input."""
    return re.sub(r"[^a-z0-9()/&,]", " ", text.lower())


def _alias_pattern(phrase: str) -> str:
    # Any run of spaces or punctuation may separate the words of an Act name ("Income-tax Act, 2025").
    return r"[^a-z0-9]+".join(re.escape(token) for token in re.findall(r"[a-z0-9]+", phrase.lower()))


@lru_cache(maxsize=1)
def _act_index() -> Tuple[re.Pattern, Dict[str, Tuple[str, ...]], Dict[str, str]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT json_extract(metadata_json, '$.act_id') AS act_id, MAX(json_extract(metadata_json, '$.act_title')) AS act_title
            FROM documents WHERE source_type = 'statute' GROUP BY act_id
            """
        ).fetchall()
    finally:
        conn.close()

    aliases: Dict[str, set] = {}
    act_years: Dict[str, str] = {}
    for row in rows:
        act_id, title = row["act_id"], row["act_title"] or ""
        if not act_id:
            continue
        full = " ".join(re.findall(r"[a-z0-9]+", re.sub(r"^\s*the\s+", "", title, flags=re.IGNORECASE).lower()))
        year = re.search(r"\s(\d{4})$", full)
        if year:
            act_years[act_id] = year.group(1)
        without_year = re.sub(r"\s\d{4}$", "", full)
        for phrase in {full, without_year}:
            if len(phrase.split()) >= 2:
                aliases.setdefault(phrase, set()).add(act_id)
    known_acts = {row["act_id"] for row in rows}
    for phrase, act_id in PROJECT_ALIASES:
        if act_id in known_acts:
            aliases.setdefault(phrase, set()).add(act_id)

    # A title without its year can name several Acts (e.g. the Income-tax Acts of 1961 and 2025). A year
    # written right after the name picks the right one; with no year, every such Act stays a candidate
    # and the reference is marked ambiguous.
    phrases = sorted(aliases, key=lambda p: (-len(p.split()), -len(p), p))
    pattern = re.compile(r"(?<![a-z0-9])(?:the\s+)?(" + "|".join(_alias_pattern(p) for p in phrases) + r")(?![a-z0-9])")
    lookup = {" ".join(p.split()): tuple(sorted(a)) for p, a in aliases.items()}
    logger.info("Legal reference index: %d Acts, %d name forms", len(known_acts), len(lookup))
    return pattern, lookup, act_years


@lru_cache(maxsize=1)
def _act_documents() -> Dict[str, Tuple[str, ...]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT doc_id, json_extract(metadata_json, '$.act_id') AS act_id FROM documents WHERE source_type = 'statute'"
        ).fetchall()
    finally:
        conn.close()
    grouped: Dict[str, List[str]] = {}
    for row in rows:
        grouped.setdefault(row["act_id"], []).append(row["doc_id"])
    return {act_id: tuple(sorted(ids)) for act_id, ids in grouped.items()}


def act_doc_ids(act_id: str) -> Tuple[str, ...]:
    """Every statute section doc_id of one Act."""
    return _act_documents().get(act_id, ())


def _act_mentions(normalized: str) -> List[Tuple[int, int, Tuple[str, ...]]]:
    pattern, lookup, act_years = _act_index()
    mentions = []
    for match in pattern.finditer(normalized):
        key = " ".join(re.findall(r"[a-z0-9]+", match.group(1)))
        acts = lookup.get(key)
        if not acts:
            continue
        end = match.end()
        if len(acts) > 1:
            year = _TRAILING_YEAR.match(normalized[end:])
            chosen = tuple(a for a in acts if year and act_years.get(a) == year.group(1))
            if chosen:
                acts, end = chosen, end + year.end()
        mentions.append((match.start(), end, acts))
    return mentions


def _section_groups(normalized: str) -> List[Dict]:
    groups = []
    for match in _SECTION_GROUP.finditer(normalized):
        numbers = [match.group("first")] + _NUMBER_IN_REST.findall(match.group("rest") or "")
        groups.append({"start": match.start(), "end": match.end(), "numbers": list(dict.fromkeys(numbers)), "acts": None})
    return groups


def _attach_acts(normalized: str, groups: List[Dict], mentions: List[Tuple[int, int, Tuple[str, ...]]]) -> None:
    for group in groups:
        following = next((m for m in mentions if m[0] >= group["end"]), None)
        if following and _GAP_BEFORE_ACT.match(normalized[group["end"]:following[0]]):
            group["acts"] = following[2]
            continue
        preceding = next((m for m in reversed(mentions) if m[1] <= group["start"]), None)
        if preceding and _GAP_AFTER_ACT.match(normalized[preceding[1]:group["start"]]):
            group["acts"] = preceding[2]

    # "Section 138 read with Section 141 of the NI Act": an unattached group inherits the Act of the
    # group it is chained to; "Section 11 of the same Act" inherits the previous group's Act.
    for index in range(len(groups) - 2, -1, -1):
        current, nxt = groups[index], groups[index + 1]
        if current["acts"] is None and nxt["acts"] and _CHAIN_GAP.match(normalized[current["end"]:nxt["start"]]):
            current["acts"] = nxt["acts"]
    for index in range(1, len(groups)):
        current = groups[index]
        if current["acts"] is None and _SAME_ACT.match(normalized[current["end"]:]):
            current["acts"] = groups[index - 1]["acts"]

    # "Section 106 of the Evidence Act ... which BSA provision corresponds to this old Section 106": a section
    # number repeated without an adjacent Act refers to the provision it was first attached to.
    for index, group in enumerate(groups):
        if group["acts"] is not None:
            continue
        earlier = next((g for g in reversed(groups[:index]) if g["acts"] and set(group["numbers"]) <= set(g["numbers"])), None)
        if earlier:
            group["acts"] = earlier["acts"]

    # "Under the Insurance Act, 1938, an appeal ... lies under Section 61A": the nearest preceding Act in the
    # same stretch of text, when no other section reference lies between them.
    for group in groups:
        if group["acts"] is not None:
            continue
        preceding = next((m for m in reversed(mentions) if m[1] <= group["start"]), None)
        if preceding and group["start"] - preceding[1] <= 250 and not any(
            preceding[1] <= other["start"] < group["start"] for other in groups if other is not group
        ):
            group["acts"] = preceding[2]

    distinct = {m[2] for m in mentions}
    if len(distinct) == 1:
        only = next(iter(distinct))
        for group in groups:
            if group["acts"] is None:
                group["acts"] = only


def _analyse(query: str):
    normalized = _normalize(query)
    mentions = _act_mentions(normalized)
    if not mentions:
        return normalized, mentions, [], []
    groups = _section_groups(normalized)
    _attach_acts(normalized, groups, mentions)

    candidates: List[Tuple[str, str, str, bool, Tuple[int, int]]] = []
    for group in groups:
        acts = group["acts"] or ()
        for act_id in acts:
            for number in group["numbers"]:
                candidates.append((act_id, number, query[group["start"]:group["end"]].strip(), len(acts) > 1, (group["start"], group["end"])))
    # "IPC 420" / "Evidence Act 65B": a bare number directly after an Act name.
    covered = [(g["start"], g["end"]) for g in groups]
    for start, end, acts in mentions:
        bare = _BARE_AFTER_ACT.match(normalized[end:])
        if not bare or any(s <= end < e or end <= s < end + bare.end() for s, e in covered):
            continue
        for act_id in acts:
            candidates.append((act_id, bare.group(1), query[start:end + bare.end()].strip(), len(acts) > 1, (start, end + bare.end())))
    return normalized, mentions, groups, candidates


def find_references(query: str) -> List[LegalReference]:
    """Explicit statute references in `query`, in order of appearance, resolved to existing documents."""
    if not query or not query.strip():
        return []
    _, _, _, candidates = _analyse(query)
    ordered: Dict[str, Tuple[str, str, str, bool]] = {}
    for act_id, number, text, ambiguous, _ in candidates:
        ordered.setdefault(make_statute_doc_id(act_id, number), (act_id, number, text, ambiguous))
    existing = {row["doc_id"] for row in get_documents_brief(ordered)}
    references = [
        LegalReference(doc_id=doc_id, act_id=act_id, section=number.upper(), matched_text=text, ambiguous=ambiguous)
        for doc_id, (act_id, number, text, ambiguous) in ordered.items() if doc_id in existing
    ]
    if references:
        logger.debug("Explicit references in %r: %s", query[:80], [r.doc_id for r in references])
    return references


def expand_mappings(references: List[LegalReference], max_per_reference: int = 3) -> List[MappedProvision]:
    """Old/new-code counterparts of `references`, taken only from stored `corresponds_to` metadata."""
    if not references:
        return []
    rows = {row["doc_id"]: row for row in get_documents_brief([r.doc_id for r in references])}
    referenced = {r.doc_id for r in references}
    proposals: List[MappedProvision] = []
    for reference in references:
        meta = json.loads((rows.get(reference.doc_id) or {}).get("metadata_json") or "{}")
        entries = [
            e for e in meta.get("corresponds_to") or []
            if isinstance(e, dict) and e.get("act") and e.get("section") and e.get("relation") not in NON_MAPPING_RELATIONS
        ]
        entries.sort(key=lambda e: -(e.get("score") or 0))
        for entry in entries[:max_per_reference]:
            proposals.append(MappedProvision(
                doc_id=make_statute_doc_id(entry["act"], entry["section"]), act_id=entry["act"], from_doc_id=reference.doc_id,
                direction=entry.get("direction"), relation=entry.get("relation"), score=entry.get("score"),
            ))
    existing = {row["doc_id"] for row in get_documents_brief({p.doc_id for p in proposals})}
    mapped: Dict[str, MappedProvision] = {}
    for proposal in proposals:
        if proposal.doc_id in existing and proposal.doc_id not in referenced:
            mapped.setdefault(proposal.doc_id, proposal)
    return list(mapped.values())


def plan_retrieval(query: str, max_mapped_per_reference: int = 3, use_mapping: bool = True) -> RetrievalPlan:
    """Evidence requirements implied by the wording of `query` (see module docstring)."""
    plan = RetrievalPlan(needs_case_law=bool(JUDICIAL_CUE.search(query or "")))
    if not query or not query.strip():
        return plan
    normalized, mentions, _, candidates = _analyse(query)
    plan.references = find_references(query)
    plan.mapped = expand_mappings(plan.references, max_mapped_per_reference) if use_mapping else []

    named_acts = {m[2][0] for m in mentions if len(m[2]) == 1}
    required_ids = set()
    for reference in plan.references:
        if reference.ambiguous:
            continue
        plan.requirements.append(Requirement(reference.doc_id, "explicit_reference", reference.matched_text))
        required_ids.add(reference.doc_id)
        for mapped in plan.mapped:
            if mapped.from_doc_id == reference.doc_id and mapped.act_id in named_acts and mapped.doc_id not in required_ids:
                plan.requirements.append(Requirement(mapped.doc_id, "mapped_counterpart", f"{mapped.relation} counterpart of {reference.doc_id}"))
                required_ids.add(mapped.doc_id)
    if plan.needs_case_law:
        plan.requirements.append(Requirement(None, "case_law_authority", JUDICIAL_CUE.search(query).group(0)))

    # Act-scoped search is for a question about one Act that does not identify the section: with several
    # Acts, or a cited section, the global search is already pointed at the right material.
    all_named_acts = {act_id for mention in mentions for act_id in mention[2]}
    if len(all_named_acts) == 1 and named_acts and not plan.references:
        plan.act_scope = sorted(named_acts)

    spans = [span for *_, span in candidates] + [(m[0], m[1]) for m in mentions]
    residual = list(query)
    for start, end in spans:
        for i in range(start, min(end, len(residual))):
            residual[i] = " "
    plan.residual_query = " ".join("".join(residual).split())
    return plan
