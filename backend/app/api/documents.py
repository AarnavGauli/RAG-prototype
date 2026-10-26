from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_session, owned_document
from app.context import AppContext
from app.errors import ConflictError, PayloadTooLarge, PdfRejected, ValidationFailed
from app.models import Citation, Document
from app.schemas import DocumentError, DocumentOut, Progress
from app.security import get_ctx, get_owner, rate_limit
from app.services import indexing, pdf, render

router = APIRouter(prefix="/documents", tags=["documents"])
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def to_out(doc: Document) -> DocumentOut:
    in_flight = doc.status in ("queued", "processing")
    return DocumentOut(
        id=doc.id,
        name=doc.name,
        size_bytes=doc.size_bytes,
        page_count=doc.page_count,
        chunk_count=doc.chunk_count,
        status=doc.status,  # type: ignore[arg-type]
        stage=doc.stage if in_flight else None,
        progress=Progress(current=doc.progress_current, total=doc.progress_total)
        if in_flight and doc.progress_total
        else None,
        error=DocumentError(code=doc.error_code or "error", message=doc.error_message or "", retryable=doc.retryable)
        if doc.status == "failed"
        else None,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def safe_display_name(raw: str | None) -> str:
    """User-supplied names are display-only: strip directories and control characters."""
    name = (raw or "document.pdf").replace("\\", "/").split("/")[-1]
    name = _CTRL.sub("", name).strip().strip(".")
    return (name or "document.pdf")[:255]


async def _spool_upload(file: UploadFile, ctx: AppContext) -> tuple[Path, int, str]:
    """Stream the upload to a temp file inside the upload dir, enforcing the size limit."""
    assert ctx.settings.upload_dir is not None
    tmp = ctx.settings.upload_dir / f".incoming-{uuid.uuid4().hex}"
    size, digest = 0, hashlib.sha256()
    try:
        with tmp.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > ctx.settings.max_upload_bytes:
                    raise PayloadTooLarge(f"The file exceeds the {ctx.settings.max_upload_mb} MB upload limit.")
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp, size, digest.hexdigest()


def _register(ctx: AppContext, session: Session, owner: str, tmp: Path, size: int, sha: str, display: str) -> Document:
    try:
        if size == 0:
            raise PdfRejected("The uploaded file is empty.", code="empty_file")
        pages = pdf.validate_pdf(tmp, ctx.settings.max_pages)
        count = session.scalar(select(func.count()).select_from(Document).where(Document.owner_id == owner)) or 0
        if count >= ctx.settings.max_documents:
            raise ConflictError(
                f"Document limit reached ({ctx.settings.max_documents}). Delete a document to upload another.",
                code="document_limit_reached",
            )
        existing = session.scalar(select(Document).where(Document.owner_id == owner, Document.sha256 == sha))
        if existing is not None:
            raise ConflictError(
                f"This file was already uploaded as '{existing.name}'.",
                code="duplicate_document",
                details={"document_id": existing.id},
            )
        stored = f"{uuid.uuid4().hex}.pdf"
        assert ctx.settings.upload_dir is not None
        os.replace(tmp, ctx.settings.upload_dir / stored)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    doc = Document(owner_id=owner, name=display, stored_name=stored, size_bytes=size, sha256=sha, page_count=pages)
    session.add(doc)
    session.commit()
    return doc


@router.post("", status_code=202, response_model=DocumentOut, dependencies=[Depends(rate_limit)])
async def upload_document(
    file: UploadFile,
    owner: str = Depends(get_owner),
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> DocumentOut:
    display = safe_display_name(file.filename)
    if not display.lower().endswith(".pdf"):
        raise ValidationFailed("Only PDF files (.pdf) are accepted.", code="unsupported_file_type")
    tmp, size, sha = await _spool_upload(file, ctx)
    doc = await run_in_threadpool(_register, ctx, session, owner, tmp, size, sha, display)
    indexing.enqueue(ctx, doc.id)
    return to_out(doc)


@router.get("", response_model=list[DocumentOut])
def list_documents(owner: str = Depends(get_owner), session: Session = Depends(get_session)) -> list[DocumentOut]:
    docs = session.scalars(select(Document).where(Document.owner_id == owner).order_by(Document.created_at.desc()))
    return [to_out(d) for d in docs]


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: str, owner: str = Depends(get_owner), session: Session = Depends(get_session)) -> DocumentOut:
    return to_out(owned_document(session, owner, doc_id))


@router.post("/{doc_id}/retry", status_code=202, response_model=DocumentOut, dependencies=[Depends(rate_limit)])
def retry_document(
    doc_id: str,
    owner: str = Depends(get_owner),
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> DocumentOut:
    doc = owned_document(session, owner, doc_id)
    if doc.status != "failed" or not doc.retryable:
        raise ConflictError("Only failed documents with a retryable error can be retried.", code="not_retryable")
    doc.status, doc.stage, doc.error_code, doc.error_message = "queued", None, None, None
    session.commit()
    indexing.enqueue(ctx, doc.id)
    return to_out(doc)


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: str,
    owner: str = Depends(get_owner),
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> Response:
    owned_document(session, owner, doc_id)
    session.commit()
    indexing.delete_document_data(ctx, doc_id)
    return Response(status_code=204)


@router.get("/{doc_id}/pages/{page}/image", response_class=Response, responses={200: {"content": {"image/png": {}}}})
def page_image(
    doc_id: str,
    page: int,
    citation: str | None = Query(None, description="Highlight this citation's excerpt"),
    owner: str = Depends(get_owner),
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> Response:
    doc = owned_document(session, owner, doc_id)
    highlight = None
    if citation:
        cit = session.get(Citation, citation)
        if cit is not None and cit.document_id == doc.id and cit.page_number == page:
            highlight = cit.excerpt
    png = render.render_page(indexing.upload_path(ctx, doc.stored_name), page, highlight)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
