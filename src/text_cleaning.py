"""
Text cleaning for PDF-extracted pages: de-hyphenation, whitespace
normalization, and repeated header/footer stripping (running headers,
page-number-only lines, etc.) that would otherwise pollute chunks and
embeddings.
"""
import re
from collections import Counter
from typing import Dict, List

from logging_config import get_logger

logger = get_logger("text_cleaning")

_PAGE_NUMBER_LINE = re.compile(r"^\s*(?:page\s*)?\d{1,4}\s*(?:of\s*\d{1,4})?\s*$", re.IGNORECASE)
_HYPHEN_LINEBREAK = re.compile(r"(\w)-\n(\w)")
_MULTI_BLANK = re.compile(r"\n{3,}")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def _dehyphenate(text: str) -> str:
    """Rejoin words split across a line break with a trailing hyphen, e.g.
    'consider-\\nation' -> 'consideration'."""
    return _HYPHEN_LINEBREAK.sub(r"\1\2", text)


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


def strip_repeated_headers_footers(pages: List[Dict], min_repeat_fraction: float = 0.4) -> List[Dict]:
    """Drop lines (running headers/footers, doc titles repeated on every page)
    that appear near-identically across a large fraction of pages."""
    if len(pages) < 4:
        return pages  # not enough pages to statistically detect repetition

    line_counts = Counter()
    for p in pages:
        lines = {ln.strip() for ln in p["text"].split("\n") if ln.strip()}
        for ln in lines:
            if 0 < len(ln) <= 120:
                line_counts[ln] += 1

    threshold = max(3, int(len(pages) * min_repeat_fraction))
    boilerplate = {ln for ln, count in line_counts.items() if count >= threshold}
    if boilerplate:
        logger.info("Stripping %d repeated header/footer line(s) across %d pages", len(boilerplate), len(pages))

    cleaned = []
    for p in pages:
        kept_lines = [ln for ln in p["text"].split("\n") if ln.strip() not in boilerplate]
        cleaned.append({"page_number": p["page_number"], "text": "\n".join(kept_lines)})
    return cleaned


def clean_page_text(text: str) -> str:
    if not text:
        return ""
    text = _dehyphenate(text)
    lines = [ln for ln in text.split("\n") if not _PAGE_NUMBER_LINE.match(ln)]
    text = "\n".join(lines)
    return _normalize_whitespace(text)


def clean_pdf_pages(pages: List[Dict]) -> List[Dict]:
    """Full cleaning pipeline: cross-page header/footer stripping, then
    per-page normalization (dehyphenation, page-number lines, whitespace)."""
    pages = strip_repeated_headers_footers(pages)
    return [{"page_number": p["page_number"], "text": clean_page_text(p["text"])} for p in pages]
