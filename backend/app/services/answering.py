"""Question answering: scope -> retrieve -> generate -> validate -> persist."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context import AppContext
from app.errors import ConflictError, ProviderError
from app.models import Citation, Conversation, Message
from app.services.citations import INSUFFICIENT_MESSAGE, ValidatedAnswer, validate_answer
from app.services.prompts import ANSWER_SCHEMA, SYSTEM_PROMPT, build_messages
from app.services.retrieval import authorised_documents, retrieve

log = logging.getLogger(__name__)

_SHORT_FOLLOW_UP_WORDS = 8


def _history(session: Session, conversation: Conversation, turns: int) -> list[tuple[str, str]]:
    if turns <= 0:
        return []
    rows = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id.desc())
            .limit(turns * 2)
        )
    )
    return [(m.role, m.content) for m in reversed(rows)]


def _retrieval_query(question: str, history: list[tuple[str, str]]) -> str:
    """Short follow-ups ("and its price?") borrow the previous user question so retrieval has a topic."""
    if len(question.split()) <= _SHORT_FOLLOW_UP_WORDS:
        previous = [content for role, content in history if role == "user"]
        if previous:
            return f"{previous[-1]}\n{question}"
    return question


def ask(
    ctx: AppContext, session: Session, owner_id: str, conversation: Conversation, question: str
) -> tuple[Message, Message]:
    ctx.llm.check_ready()  # fail fast with a configuration message
    documents = authorised_documents(session, owner_id, conversation)
    if not documents:
        raise ConflictError(
            "There are no indexed documents in scope for this conversation. Upload a PDF and wait for "
            "indexing to finish, or adjust the conversation's document selection.",
            code="no_ready_documents",
        )
    history = _history(session, conversation, ctx.settings.history_max_turns)
    result = retrieve(ctx, session, query=_retrieval_query(question, history), documents=documents)

    meta: dict = {
        "retrieved": len(result.chunks),
        "candidates": result.candidates,
        "top_score": round(result.top_score, 4) if result.top_score is not None else None,
        "min_score": ctx.settings.min_score,
        "embedding_model": ctx.embedder.model_id,
    }
    if not result.chunks:
        validated = ValidatedAnswer(False, INSUFFICIENT_MESSAGE, [], reason="no_relevant_passages")
    else:
        raw = ctx.llm.generate_structured(
            system=SYSTEM_PROMPT,
            messages=build_messages(question, result.chunks, history),
            schema=ANSWER_SCHEMA,
            max_tokens=ctx.settings.llm_max_output_tokens,
        )
        if not isinstance(raw, dict):
            raise ProviderError("The model returned an unexpected response.", code="llm_bad_response")
        validated = validate_answer(raw, result.chunks)
        meta["model"] = ctx.llm.model
    if validated.reason:
        meta["reason"] = validated.reason

    user_msg = Message(conversation_id=conversation.id, role="user", content=question)
    session.add(user_msg)
    session.flush()
    assistant = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=validated.text,
        status="ok" if validated.sufficient else "insufficient_evidence",
        meta=meta,
    )
    session.add(assistant)
    session.flush()
    for i, c in enumerate(validated.citations):
        session.add(
            Citation(
                message_id=assistant.id,
                document_id=c.chunk.document_id,
                chunk_source_id=c.chunk.source_id,
                label=c.label,
                ordinal=i,
                document_name=c.chunk.document_name,
                page_number=c.chunk.page_number,
                excerpt=c.excerpt,
                quote_verified=c.quote_verified,
                score=round(c.chunk.score, 4),
            )
        )
    if conversation.title == "New conversation":
        conversation.title = (question[:60] + "…") if len(question) > 60 else question
    conversation.updated_at = datetime.now(UTC)
    session.flush()
    session.refresh(assistant)
    return user_msg, assistant
