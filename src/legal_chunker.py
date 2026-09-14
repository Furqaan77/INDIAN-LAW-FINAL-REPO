"""
Structure-aware chunking, shared by the case-law path (chunk_embed.py, JSON
judgments with FACTS/ISSUE/REASONING/HOLDING markers) and the PDF path
(ingest_pdf.py, arbitrary statutes/commentaries/judgments as PDF).

Two-stage, offset-preserving design:
  1. split_into_sections() — split on structural headings (regex-driven,
     pluggable per document type) into (label, text, start_offset, end_offset).
     Offsets are preserved so callers with page-boundary information (PDFs)
     can recover which page(s) each chunk came from.
  2. enforce_chunk_size() — any section still too long for one embedding
     chunk is sliced into overlapping windows, offsets preserved throughout.

Heading detection for PDFs is necessarily heuristic — legal PDFs vary wildly
in formatting. When no headings are detected, the whole document falls back
to plain overlapping-window chunking, which always produces usable chunks.
"""
import re
from typing import List, Optional, Tuple

Section = Tuple[Optional[str], str, int, int]  # (label, text, start_offset, end_offset)

CASE_LAW_SECTION_MARKERS = ["FACTS:", "ISSUE:", "REASONING:", "HOLDING:"]
CASE_LAW_SECTION_PATTERN = re.compile("(?:" + "|".join(re.escape(m) for m in CASE_LAW_SECTION_MARKERS) + ")")

# Heuristic heading detector for statutes / judgments / commentaries extracted from PDF.
# Matches lines like "CHAPTER III", "SECTION 138.", "Article 21 - Right to Life",
# or numbered headings like "3.2 Limitation Period".
PDF_HEADING_PATTERN = re.compile(
    r"(?m)^[ \t]*(?:"
    r"CHAPTER\s+[IVXLCDM\d]+[A-Za-z]?\.?[ \t]*[-:]?[ \t]*.{0,80}"
    r"|PART\s+[IVXLCDM\d]+[A-Za-z]?\.?[ \t]*[-:]?[ \t]*.{0,80}"
    r"|SECTION\s+\d+[A-Za-z]?\.?[ \t]*[-:]?[ \t]*.{0,80}"
    r"|ARTICLE\s+\d+[A-Za-z]?\.?[ \t]*[-:]?[ \t]*.{0,80}"
    r"|\d{1,3}(?:\.\d{1,2}){0,2}\.?[ \t]+[A-Z][^\n]{2,80}"
    r")[ \t]*$"
)


def split_into_sections(text: str, heading_pattern: re.Pattern) -> List[Section]:
    """Split `text` at heading_pattern matches. Heading text itself is stripped
    out and becomes the section label; everything between one heading and the
    next becomes that section's body, offsets relative to the original text."""
    if not text:
        return []

    matches = list(heading_pattern.finditer(text))
    if not matches:
        return [(None, text, 0, len(text))] if text.strip() else []

    sections: List[Section] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()]
        if preamble.strip():
            sections.append((None, preamble, 0, matches[0].start()))

    for i, m in enumerate(matches):
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        label = m.group(0).strip().rstrip(":").strip() or None
        body = text[body_start:body_end]
        if body.strip():
            sections.append((label, body, body_start, body_end))

    return sections


def enforce_chunk_size(sections: List[Section], target_size: int = 1200, overlap: int = 150) -> List[Section]:
    """Slice any section longer than target_size into overlapping windows."""
    result: List[Section] = []
    for label, text, start, end in sections:
        if len(text) <= target_size:
            result.append((label, text, start, end))
            continue
        pos = 0
        n = len(text)
        while pos < n:
            chunk_end = min(pos + target_size, n)
            result.append((label, text[pos:chunk_end], start + pos, start + chunk_end))
            if chunk_end >= n:
                break
            pos += target_size - overlap
    return result


def chunk_case_law_text(text: str, target_size: int = 1200, overlap: int = 150) -> List[Section]:
    """FACTS/ISSUE/REASONING/HOLDING-aware chunking for structured case-law text,
    falling back to overlapping windows when those markers aren't present."""
    sections = split_into_sections(text, CASE_LAW_SECTION_PATTERN)
    return enforce_chunk_size(sections, target_size, overlap)


def chunk_pdf_text(text: str, target_size: int = 1200, overlap: int = 150) -> List[Section]:
    """Heading-aware chunking for PDF-derived text, falling back to overlapping
    windows when no recognizable legal headings are present."""
    sections = split_into_sections(text, PDF_HEADING_PATTERN)
    return enforce_chunk_size(sections, target_size, overlap)
