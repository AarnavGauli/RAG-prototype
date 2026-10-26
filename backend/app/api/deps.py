from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.context import AppContext
from app.errors import NotFoundError
from app.models import Conversation, Document
from app.security import get_ctx, get_owner


def get_session(ctx: AppContext = Depends(get_ctx)) -> Iterator[Session]:
    session = ctx.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def owned_document(session: Session, owner_id: str, doc_id: str) -> Document:
    doc = session.get(Document, doc_id)
    if doc is None or doc.owner_id != owner_id:  # identical response for "missing" and "not yours"
        raise NotFoundError("Document not found.", code="document_not_found")
    return doc


def owned_conversation(session: Session, owner_id: str, conv_id: str) -> Conversation:
    conv = session.get(Conversation, conv_id)
    if conv is None or conv.owner_id != owner_id:
        raise NotFoundError("Conversation not found.", code="conversation_not_found")
    return conv


__all__ = ["Depends", "get_ctx", "get_owner", "get_session", "owned_conversation", "owned_document"]
