"""Scoped vector retrieval with thresholding, de-duplication and a context budget."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context import AppContext
from app.models import Chunk, Conversation, Document


@dataclass
class RetrievedChunk:
    chunk_id: int
    source_id: str
    document_id: str
    document_name: str
    page_number: int
    char_start: int
    char_end: int
    text: str
    score: float
    token_count: int


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    candidates: int  # vector hits before threshold
    top_score: float | None


def authorised_documents(
    session: Session, owner_id: str, conversation: Conversation | None = None, document_ids: list[str] | None = None
) -> list[Document]:
    """Ready documents owned by ``owner_id``, narrowed to the conversation scope / explicit ids."""
    stmt = select(Document).where(Document.owner_id == owner_id, Document.status == "ready")
    wanted = set(document_ids or [])
    if conversation is not None:
        wanted |= {cd.document_id for cd in conversation.scope}
    if wanted:
        stmt = stmt.where(Document.id.in_(wanted))
    return list(session.scalars(stmt))


_WORD = re.compile(r"\w+", re.UNICODE)


def _token_set(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)}


def _near_duplicate(a: set[str], b: set[str], threshold: float) -> bool:
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= threshold


def retrieve(
    ctx: AppContext,
    session: Session,
    *,
    query: str,
    documents: list[Document],
    top_k: int | None = None,
    min_score: float | None = None,
    query_vector: np.ndarray | None = None,
) -> RetrievalResult:
    settings = ctx.settings
    k = min(top_k or settings.retrieval_top_k, settings.retrieval_max_top_k)
    threshold = settings.min_score if min_score is None else min_score
    if not documents:
        return RetrievalResult([], 0, None)
    doc_by_id = {d.id: d for d in documents}

    allowed = {int(i) for i in session.scalars(select(Chunk.id).where(Chunk.document_id.in_(doc_by_id)))}
    qvec = query_vector if query_vector is not None else ctx.embedder.embed_query(query)
    hits = ctx.vectors.search(qvec, min(max(k * 4, 20), max(len(allowed), 1)), allowed)
    if not hits:
        return RetrievalResult([], 0, None)

    rows = {c.id: c for c in session.scalars(select(Chunk).where(Chunk.id.in_([h[0] for h in hits])))}
    chosen: list[RetrievedChunk] = []
    token_sets: list[set[str]] = []
    budget = settings.context_max_tokens
    for chunk_id, score in hits:  # already sorted by score
        if score < threshold or len(chosen) >= k:
            break
        row = rows.get(chunk_id)
        if row is None or row.document_id not in doc_by_id:  # defensive scope check
            continue
        tokens = _token_set(row.text)
        if any(_near_duplicate(tokens, other, settings.retrieval_dedupe_similarity) for other in token_sets):
            continue
        if chosen and budget - row.token_count < 0:
            continue
        budget -= row.token_count
        token_sets.append(tokens)
        chosen.append(
            RetrievedChunk(
                chunk_id=row.id,
                source_id=row.source_id,
                document_id=row.document_id,
                document_name=doc_by_id[row.document_id].name,
                page_number=row.page_number,
                char_start=row.char_start,
                char_end=row.char_end,
                text=row.text,
                score=score,
                token_count=row.token_count,
            )
        )
    return RetrievalResult(chosen, len(hits), hits[0][1])
