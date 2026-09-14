"""
PDF text extraction.

Extracts per-page text using pypdf. Deliberately simple (no OCR, no
layout/table reconstruction) — text-layer-only extraction is sufficient for
the current POC scope. Scanned/image-only PDFs yield empty pages and are
logged as warnings rather than silently ingested as empty documents, so they
can be flagged for an OCR pass later.
"""
import os
from typing import Dict, List

from logging_config import get_logger

logger = get_logger("pdf_extract")


def extract_pdf_pages(path: str) -> List[Dict]:
    """Returns [{"page_number": int (1-indexed), "text": str}, ...]."""
    from pypdf import PdfReader

    if not os.path.exists(path):
        raise FileNotFoundError(f"PDF not found: {path}")

    try:
        reader = PdfReader(path)
    except Exception:
        logger.exception("Failed to open PDF: %s", path)
        raise

    pages = []
    empty_pages = 0
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            logger.warning("Failed to extract text from page %d of %s", i, path, exc_info=True)
            text = ""
        if not text.strip():
            empty_pages += 1
        pages.append({"page_number": i, "text": text})

    if empty_pages:
        logger.warning(
            "%d/%d pages had no extractable text in %s "
            "(likely scanned images — OCR is not implemented in this POC)",
            empty_pages, len(pages), path,
        )
    return pages
