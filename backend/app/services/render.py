"""Render a PDF page to PNG, optionally highlighting an excerpt. Read-only; PDF content is never executed."""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from app.errors import NotFoundError


def _search(page: pymupdf.Page, text: str) -> list[pymupdf.Quad]:
    quads = page.search_for(text, quads=True)
    if quads:
        return quads
    words = text.split()
    found: list[pymupdf.Quad] = []
    window = 6
    for i in range(0, len(words), window):
        phrase = " ".join(words[i : i + window])
        if len(phrase) >= 12:
            found.extend(page.search_for(phrase, quads=True))
    return found


def render_page(path: Path, page_number: int, highlight: str | None = None, zoom: float = 1.6) -> bytes:
    doc = pymupdf.open(str(path))
    try:
        if not 1 <= page_number <= doc.page_count:
            raise NotFoundError("Page not found in this document.", code="page_not_found")
        page = doc[page_number - 1]
        if highlight:
            cleaned = re.sub(r"\s+", " ", highlight.replace("…", " ")).strip()
            quads = _search(page, cleaned) if cleaned else []
            if quads:
                annot = page.add_highlight_annot(quads=quads)
                annot.set_colors(stroke=(1, 0.85, 0.2))
                annot.update()
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=True)
        return pix.tobytes("png")
    finally:
        doc.close()
