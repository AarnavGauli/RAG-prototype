"""Validation of model output against the evidence that was actually supplied for the answer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.prompts import label_for
from app.services.retrieval import RetrievedChunk

INSUFFICIENT_MESSAGE = "I couldn't find enough evidence in the selected documents to answer that question."
_MARKER = re.compile(r"\[(S\d+)\]")
_WS = re.compile(r"\s+")


def _squash(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


@dataclass
class ValidatedCitation:
    label: str
    chunk: RetrievedChunk
    excerpt: str
    quote_verified: bool


@dataclass
class ValidatedAnswer:
    sufficient: bool
    text: str
    citations: list[ValidatedCitation]
    reason: str | None = None  # why an answer was downgraded (for logs/meta; never user content)


def make_excerpt(chunk_text: str, quote: str | None, max_chars: int = 420) -> tuple[str, bool]:
    """Return (excerpt, quote_verified). A quote is verified only if it is a substring of the chunk."""
    squashed_chunk = _squash(chunk_text)
    if quote and len(quote.strip()) >= 8 and _squash(quote) in squashed_chunk:
        # locate in the original text (whitespace-insensitive) to preserve original casing
        pattern = r"\s+".join(re.escape(w) for w in quote.split())
        m = re.search(pattern, chunk_text, re.IGNORECASE)
        if m:
            start = max(0, m.start() - 120)
            end = min(len(chunk_text), m.end() + 120)
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(chunk_text) else ""
            return f"{prefix}{chunk_text[start:end].strip()}{suffix}", True
    text = chunk_text.strip()
    return (text if len(text) <= max_chars else text[:max_chars].rstrip() + "…"), False


def validate_answer(raw: dict[str, Any], chunks: list[RetrievedChunk]) -> ValidatedAnswer:
    labels = {label_for(i): c for i, c in enumerate(chunks)}
    answer = raw.get("answer")
    answer = answer.strip() if isinstance(answer, str) else ""
    sufficient = raw.get("sufficient_evidence") is True

    quotes: dict[str, str] = {}
    cited: list[str] = []
    for item in raw.get("citations") or []:
        if isinstance(item, str):
            item = {"source": item}
        if not isinstance(item, dict):
            continue
        src = str(item.get("source", "")).strip().strip("[]")
        if src in labels and src not in cited:
            cited.append(src)
            if isinstance(item.get("quote"), str):
                quotes[src] = item["quote"]
    for m in _MARKER.finditer(answer):  # labels used inline count as citations only if they exist
        if m.group(1) in labels and m.group(1) not in cited:
            cited.append(m.group(1))

    # strip invalid markers the model invented (e.g. [S9]), together with the space before them
    answer = re.sub(r"[ \t]*\[(S\d+)\]", lambda m: m.group(0) if m.group(1) in labels else "", answer).strip()

    if not sufficient:
        return ValidatedAnswer(False, answer or INSUFFICIENT_MESSAGE, [], reason="model_reported_insufficient")
    if not answer:
        return ValidatedAnswer(False, INSUFFICIENT_MESSAGE, [], reason="empty_answer")
    if not cited:
        return ValidatedAnswer(False, INSUFFICIENT_MESSAGE, [], reason="no_valid_citations")

    cited.sort(key=lambda s: int(s[1:]))
    out = []
    for label in cited:
        chunk = labels[label]
        excerpt, verified = make_excerpt(chunk.text, quotes.get(label))
        out.append(ValidatedCitation(label, chunk, excerpt, verified))
    return ValidatedAnswer(True, answer, out)
