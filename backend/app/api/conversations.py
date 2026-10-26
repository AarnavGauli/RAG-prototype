from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_session, owned_conversation
from app.context import AppContext
from app.errors import NotFoundError, ValidationFailed
from app.models import Citation, Conversation, ConversationDocument, Document, Message
from app.schemas import (
    AnswerOut,
    CitationDetail,
    CitationOut,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    MessageMeta,
    MessageOut,
    MessagePage,
    QuestionIn,
)
from app.security import get_ctx, get_owner, rate_limit
from app.services import answering, indexing

router = APIRouter(tags=["conversations"])


def conv_out(conv: Conversation) -> ConversationOut:
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        document_ids=sorted(cd.document_id for cd in conv.scope),
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def message_out(m: Message) -> MessageOut:
    meta = m.meta or {}
    return MessageOut(
        id=m.id,
        role=m.role,  # type: ignore[arg-type]
        content=m.content,
        status=m.status,  # type: ignore[arg-type]
        created_at=m.created_at,
        citations=[CitationOut.model_validate(c) for c in m.citations],
        meta=MessageMeta(retrieved=meta.get("retrieved"), top_score=meta.get("top_score"), reason=meta.get("reason"))
        if m.role == "assistant"
        else None,
    )


def _set_scope(session: Session, owner: str, conv: Conversation, document_ids: list[str]) -> None:
    ids = set(document_ids)
    if ids:
        owned = set(session.scalars(select(Document.id).where(Document.owner_id == owner, Document.id.in_(ids))))
        if owned != ids:
            raise ValidationFailed("One or more selected documents do not exist.", code="unknown_document")
    conv.scope = [ConversationDocument(conversation_id=conv.id, document_id=i) for i in sorted(ids)]


@router.post("/conversations", status_code=201, response_model=ConversationOut)
def create_conversation(
    body: ConversationCreate, owner: str = Depends(get_owner), session: Session = Depends(get_session)
) -> ConversationOut:
    title = (body.title or "").strip() or "New conversation"
    conv = Conversation(owner_id=owner, title=title)
    session.add(conv)
    session.flush()
    _set_scope(session, owner, conv, body.document_ids)
    session.flush()
    session.refresh(conv)
    return conv_out(conv)


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    owner: str = Depends(get_owner), session: Session = Depends(get_session)
) -> list[ConversationOut]:
    rows = session.scalars(
        select(Conversation)
        .where(Conversation.owner_id == owner)
        .options(selectinload(Conversation.scope))
        .order_by(Conversation.updated_at.desc())
    )
    return [conv_out(c) for c in rows]


@router.get("/conversations/{conv_id}", response_model=ConversationOut)
def get_conversation(
    conv_id: str, owner: str = Depends(get_owner), session: Session = Depends(get_session)
) -> ConversationOut:
    return conv_out(owned_conversation(session, owner, conv_id))


@router.patch("/conversations/{conv_id}", response_model=ConversationOut)
def update_conversation(
    conv_id: str, body: ConversationUpdate, owner: str = Depends(get_owner), session: Session = Depends(get_session)
) -> ConversationOut:
    conv = owned_conversation(session, owner, conv_id)
    if body.title is not None:
        conv.title = body.title
    if body.document_ids is not None:
        _set_scope(session, owner, conv, body.document_ids)
    session.flush()
    session.refresh(conv)
    return conv_out(conv)


@router.delete("/conversations/{conv_id}", status_code=204)
def delete_conversation(
    conv_id: str, owner: str = Depends(get_owner), session: Session = Depends(get_session)
) -> Response:
    session.delete(owned_conversation(session, owner, conv_id))
    return Response(status_code=204)


@router.get("/conversations/{conv_id}/messages", response_model=MessagePage)
def list_messages(
    conv_id: str,
    limit: int = Query(50, ge=1, le=200),
    before: str | None = Query(None, description="Return messages older than this message id"),
    owner: str = Depends(get_owner),
    session: Session = Depends(get_session),
) -> MessagePage:
    owned_conversation(session, owner, conv_id)
    stmt = (
        select(Message)
        .where(Message.conversation_id == conv_id)
        .options(selectinload(Message.citations))
        .order_by(Message.id.desc())
        .limit(limit + 1)
    )
    if before:
        stmt = stmt.where(Message.id < before)
    rows = list(session.scalars(stmt))
    has_more = len(rows) > limit
    return MessagePage(messages=[message_out(m) for m in reversed(rows[:limit])], has_more=has_more)


@router.post(
    "/conversations/{conv_id}/messages", response_model=AnswerOut, status_code=201, dependencies=[Depends(rate_limit)]
)
def ask_question(
    conv_id: str,
    body: QuestionIn,
    owner: str = Depends(get_owner),
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> AnswerOut:
    if len(body.content) > ctx.settings.max_question_chars:
        raise ValidationFailed(
            f"Questions are limited to {ctx.settings.max_question_chars} characters.", code="question_too_long"
        )
    conv = owned_conversation(session, owner, conv_id)
    user_msg, assistant = answering.ask(ctx, session, owner, conv, body.content)
    session.commit()
    session.refresh(assistant)
    return AnswerOut(user_message=message_out(user_msg), assistant_message=message_out(assistant))


@router.get("/citations/{citation_id}", response_model=CitationDetail)
def inspect_citation(
    citation_id: str,
    owner: str = Depends(get_owner),
    ctx: AppContext = Depends(get_ctx),
    session: Session = Depends(get_session),
) -> CitationDetail:
    from app.models import Chunk

    cit = session.get(Citation, citation_id)
    if cit is None:
        raise NotFoundError("Citation not found.", code="citation_not_found")
    msg = session.get(Message, cit.message_id)
    conv = session.get(Conversation, msg.conversation_id) if msg else None
    doc = session.get(Document, cit.document_id)
    if conv is None or conv.owner_id != owner or doc is None or doc.owner_id != owner:
        raise NotFoundError("Citation not found.", code="citation_not_found")
    chunk = session.scalar(select(Chunk).where(Chunk.source_id == cit.chunk_source_id, Chunk.document_id == doc.id))
    if chunk is None:
        raise NotFoundError("The cited passage is no longer indexed.", code="citation_source_missing")
    return CitationDetail(
        **CitationOut.model_validate(cit).model_dump(),
        chunk_text=chunk.text,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        page_image_url=f"/api/v1/documents/{doc.id}/pages/{cit.page_number}/image?citation={cit.id}",
        message_id=cit.message_id,
    )


__all__ = ["indexing", "router"]
