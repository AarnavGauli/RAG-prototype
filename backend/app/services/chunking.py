"""Sentence/paragraph-aware chunking with overlap.

Token counts are *estimated* (word and punctuation pieces) so chunking has no model dependency; the
estimate is close to WordPiece counts, which is what the default embedding model uses.
Trade-offs: larger chunks keep more context per hit but dilute the embedding and cost more prompt tokens;
smaller chunks retrieve precisely but can lose the surrounding explanation. Overlap protects facts that
straddle a boundary at the price of some duplicated text (handled by retrieval-time de-duplication).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.pdf import PageText

_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[A-Z0-9\"'(\[])")


def estimate_tokens(text: str) -> int:
    return len(_TOKEN.findall(text))


@dataclass
class ChunkDraft:
    page_number: int
    chunk_index: int  # filled in by chunk_pages
    char_start: int
    char_end: int
    text: str
    token_count: int


def _segments(text: str, limit: int) -> list[tuple[int, int]]:
    """Split page text into (start, end) segments: paragraphs -> sentences -> word windows for huge runs."""
    spans: list[tuple[int, int]] = []
    for para in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", text):
        p_start, p_end = para.start(), para.end()
        para_text = para.group()
        if estimate_tokens(para_text) <= limit:
            spans.append((p_start, p_end))
            continue
        pos = 0
        for m in [*list(_SENTENCE_END.finditer(para_text)), None]:
            end = m.end() if m else len(para_text)
            if end > pos:
                spans.append((p_start + pos, p_start + end))
            pos = end
    # fallback: sentences that are still longer than the limit are cut on word boundaries
    out: list[tuple[int, int]] = []
    for s, e in spans:
        seg = text[s:e]
        if estimate_tokens(seg) <= limit:
            out.append((s, e))
            continue
        words = list(re.finditer(r"\S+", seg))
        step = max(1, limit // 2)  # words are >= 1 token each; halve to stay under the limit
        for i in range(0, len(words), step):
            window = words[i : i + step]
            out.append((s + window[0].start(), s + window[-1].end()))
    return [(s, e) for s, e in out if text[s:e].strip()]


def chunk_page(page: PageText, size: int, overlap: int) -> list[ChunkDraft]:
    text = page.text
    if not text:
        return []
    segs = _segments(text, size)
    sizes = [estimate_tokens(text[s:e]) for s, e in segs]
    chunks: list[ChunkDraft] = []
    i = 0
    while i < len(segs):
        j, total = i, 0
        while j < len(segs) and (total + sizes[j] <= size or j == i):
            total += sizes[j]
            j += 1
        start, end = segs[i][0], segs[j - 1][1]
        chunk_text = text[start:end]
        chunks.append(ChunkDraft(page.page_number, 0, start, end, chunk_text, estimate_tokens(chunk_text)))
        if j >= len(segs):
            break
        # next chunk starts with trailing segments totalling <= overlap tokens (always advances)
        k, carried = j, 0
        while k - 1 > i and carried + sizes[k - 1] <= overlap:
            carried += sizes[k - 1]
            k -= 1
        i = k if k > i else j
    return chunks


def chunk_pages(pages: list[PageText], size: int, overlap: int) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for page in pages:
        drafts.extend(chunk_page(page, size, overlap))
    for index, d in enumerate(drafts):
        d.chunk_index = index
    return drafts
