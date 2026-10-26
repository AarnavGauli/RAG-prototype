"""PDF validation and page-by-page text extraction (PyMuPDF). Embedded content is never executed."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.errors import PdfRejected

pymupdf.TOOLS.mupdf_display_errors(False)

_WS = re.compile(r"[ \t\f\v ]+")
_BLANKS = re.compile(r"\n{3,}")


@dataclass
class PageText:
    page_number: int  # 1-based
    text: str


def normalise_text(text: str) -> str:
    """NFC-normalise, strip control characters, collapse irregular whitespace, keep paragraph breaks."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    # re-join words hyphenated across line breaks ("exam-\nple" -> "example")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    lines = [_WS.sub(" ", ln).strip() for ln in text.split("\n")]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def validate_pdf(path: Path, max_pages: int) -> int:
    """Cheap structural validation performed in the request path. Returns the page count."""
    with path.open("rb") as fh:
        if b"%PDF-" not in fh.read(1024):
            raise PdfRejected("This file is not a PDF (missing %PDF header).", code="not_a_pdf")
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        raise PdfRejected("The PDF is malformed or unreadable.", code="malformed_pdf") from exc
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise PdfRejected("Password-protected PDFs are not supported.", code="encrypted_pdf")
        if doc.page_count == 0:
            raise PdfRejected("The PDF contains no pages.", code="empty_pdf")
        if doc.page_count > max_pages:
            raise PdfRejected(f"The PDF has {doc.page_count} pages; the limit is {max_pages}.", code="too_many_pages")
        return doc.page_count
    finally:
        doc.close()


def extract_pages(path: Path) -> list[PageText]:
    """Extract text for every page (including blank ones, with empty text)."""
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        raise PdfRejected("The PDF is malformed or unreadable.", code="malformed_pdf") from exc
    pages: list[PageText] = []
    try:
        for index in range(doc.page_count):
            try:
                raw = doc[index].get_text("text", sort=True)
            except Exception:
                raw = ""
            pages.append(PageText(index + 1, normalise_text(raw)))
    finally:
        doc.close()
    return pages
