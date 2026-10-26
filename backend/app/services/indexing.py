"""Document processing pipeline: extract -> chunk -> embed -> persist -> index.

Idempotent: every run first removes any chunks/vectors from previous attempts for the document, so retries and
restarts are safe. Embeddings are computed before any state is written, so a provider failure leaves no
partial index. SQLite is committed first; if the vector write then fails the index is repaired by ``reconcile``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.context import AppContext
from app.db import session_scope
from app.errors import AppError, PdfRejected
from app.models import Chunk, Document
from app.services import pdf
from app.services.chunking import chunk_pages

log = logging.getLogger(__name__)

NON_RETRYABLE = {"no_extractable_text", "malformed_pdf", "encrypted_pdf", "empty_pdf", "too_many_pages", "not_a_pdf"}


def upload_path(ctx: AppContext, stored_name: str) -> Path:
    # stored_name is generated server-side; resolve defensively anyway
    assert ctx.settings.upload_dir is not None
    base = ctx.settings.upload_dir.resolve()
    path = (base / stored_name).resolve()
    if base not in path.parents:
        raise AppError("Invalid storage path", code="invalid_path", status_code=500)
    return path


def _set(ctx: AppContext, doc_id: str, **fields: object) -> None:
    with session_scope(ctx.session_factory) as s:
        s.execute(update(Document).where(Document.id == doc_id).values(**fields))


def _remove_chunks(ctx: AppContext, session: Session, doc_id: str) -> None:
    ids = list(session.scalars(select(Chunk.id).where(Chunk.document_id == doc_id)))
    if ids:
        ctx.vectors.remove(ids)
        session.query(Chunk).filter(Chunk.document_id == doc_id).delete(synchronize_session=False)


def process_document(ctx: AppContext, doc_id: str) -> None:
    """Run the pipeline for one document, recording success or failure on the document row."""
    with session_scope(ctx.session_factory) as s:
        doc = s.get(Document, doc_id)
        if doc is None:
            return
        stored_name = doc.stored_name
        _remove_chunks(ctx, s, doc_id)
        doc.status, doc.stage = "processing", "extracting"
        doc.chunk_count, doc.progress_current, doc.progress_total = 0, 0, 0
        doc.error_code = doc.error_message = None
        doc.retryable = False
    try:
        pages = pdf.extract_pages(upload_path(ctx, stored_name))
        if not any(p.text for p in pages):
            raise PdfRejected(
                "No extractable text was found. This looks like a scanned/image-only PDF; OCR is not "
                "supported in this version.",
                code="no_extractable_text",
            )
        drafts = chunk_pages(pages, ctx.settings.chunk_size_tokens, ctx.settings.chunk_overlap_tokens)
        _set(ctx, doc_id, page_count=len(pages), stage="embedding", progress_current=0, progress_total=len(drafts))

        batch = ctx.settings.embedding_batch_size
        parts: list[np.ndarray] = []
        for i in range(0, len(drafts), batch):
            parts.append(ctx.embedder.embed_documents([d.text for d in drafts[i : i + batch]]))
            _set(ctx, doc_id, progress_current=min(i + batch, len(drafts)))
        vectors = np.vstack(parts)

        _set(ctx, doc_id, stage="indexing")
        with session_scope(ctx.session_factory) as s:
            rows = [
                Chunk(
                    document_id=doc_id,
                    page_number=d.page_number,
                    chunk_index=d.chunk_index,
                    char_start=d.char_start,
                    char_end=d.char_end,
                    token_count=d.token_count,
                    text=d.text,
                    embedding=vectors[i].astype(np.float32).tobytes(),
                )
                for i, d in enumerate(drafts)
            ]
            s.add_all(rows)
            s.flush()
            ids = [r.id for r in rows]
            doc = s.get(Document, doc_id)
            assert doc is not None  # a concurrent delete fails the flush above and lands in the error path
            doc.status, doc.stage = "ready", None
            doc.chunk_count = len(rows)
            doc.embedding_model = ctx.embedder.model_id
            try:
                ctx.vectors.add(ids, vectors)
            except Exception:
                ctx.vectors.remove(ids)
                raise
        log.info("Indexed document %s (%d pages, %d chunks)", doc_id, len(pages), len(drafts))
    except AppError as exc:
        _fail(ctx, doc_id, exc.code, exc.message, retryable=exc.code not in NON_RETRYABLE)
    except Exception:
        log.exception("Indexing failed for %s", doc_id)
        _fail(ctx, doc_id, "indexing_failed", "Indexing failed unexpectedly. You can retry.", retryable=True)


def _fail(ctx: AppContext, doc_id: str, code: str, message: str, *, retryable: bool) -> None:
    with session_scope(ctx.session_factory) as s:
        doc = s.get(Document, doc_id)
        if doc is None:
            return
        _remove_chunks(ctx, s, doc_id)
        doc.status, doc.stage = "failed", None
        doc.error_code, doc.error_message, doc.retryable = code, message[:500], retryable
        doc.chunk_count = 0


def enqueue(ctx: AppContext, doc_id: str) -> None:
    ctx.executor.submit(process_document, ctx, doc_id)


def delete_document_data(ctx: AppContext, doc_id: str) -> None:
    """Remove vectors, chunks, relational rows and the stored file for a document."""
    with session_scope(ctx.session_factory) as s:
        doc = s.get(Document, doc_id)
        if doc is None:
            return
        stored_name = doc.stored_name
        _remove_chunks(ctx, s, doc_id)
        s.delete(doc)
    try:
        upload_path(ctx, stored_name).unlink(missing_ok=True)
    except OSError:
        log.warning("Could not remove stored file for %s", doc_id)


def recover_on_startup(ctx: AppContext) -> None:
    """Re-queue interrupted work, drop documents indexed with another embedding model, repair the index."""
    with session_scope(ctx.session_factory) as s:
        stale_ids: list[str] = []
        for doc in s.scalars(select(Document).where(Document.status == "ready")):
            if doc.embedding_model and doc.embedding_model != ctx.embedder.model_id:
                _remove_chunks(ctx, s, doc.id)
                doc.status, doc.chunk_count = "failed", 0
                doc.error_code = "embedding_model_changed"
                doc.error_message = "The embedding model changed since this document was indexed. Retry to re-index it."
                doc.retryable = True
                stale_ids.append(doc.id)
        s.flush()
        expected = {
            cid: emb
            for cid, emb in s.execute(
                select(Chunk.id, Chunk.embedding).join(Document).where(Document.status == "ready")
            )
        }
        pending = list(s.scalars(select(Document.id).where(Document.status.in_(["queued", "processing"]))))
    added, removed = ctx.vectors.reconcile(expected)
    if added or removed:
        log.info("Vector index reconciled (added=%d, removed=%d)", added, removed)
    for doc_id in pending:
        enqueue(ctx, doc_id)
