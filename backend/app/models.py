"""Relational schema. Embeddings are stored with chunks so the FAISS index is always rebuildable."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime, TypeDecorator

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def new_sortable_id(prefix: str) -> str:
    """Time-ordered id (lexicographic order == creation order), used for messages."""
    return f"{prefix}_{time.time_ns():x}{uuid.uuid4().hex[:6]}"


class TZDateTime(TypeDecorator):
    """Timezone-aware datetimes; stored as naive UTC (SQLite drops tzinfo)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("owner_id", "sha256", name="uq_document_owner_sha"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("doc"))
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|processing|ready|failed
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool] = mapped_column(default=False)
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=_now, onupdate=_now)

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_doc_page", "document_id", "page_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # FAISS id
    source_id: Mapped[str] = mapped_column(String(40), unique=True, default=lambda: new_id("chk"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)  # 1-based
    chunk_index: Mapped[int] = mapped_column(Integer)  # order within the document
    char_start: Mapped[int] = mapped_column(Integer)  # offsets into the normalised page text
    char_end: Mapped[int] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[bytes] = mapped_column(LargeBinary)  # float32, L2-normalised

    document: Mapped[Document] = relationship(back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("conv"))
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=_now, onupdate=_now)

    scope: Mapped[list[ConversationDocument]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.id",
    )


class ConversationDocument(Base):
    """Documents a conversation is restricted to. No rows => all of the owner's documents."""

    __tablename__ = "conversation_documents"

    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conv", "conversation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_sortable_id("msg"))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # user|assistant
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="ok")  # ok|insufficient_evidence
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    citations: Mapped[list[Citation]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Citation.ordinal",
    )


class Citation(Base):
    """A validated reference from an answer to a chunk that was supplied to the model for that answer."""

    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cit"))
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_source_id: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(8))  # "S1" as used in the answer text
    ordinal: Mapped[int] = mapped_column(Integer)
    document_name: Mapped[str] = mapped_column(String(255))
    page_number: Mapped[int] = mapped_column(Integer)
    excerpt: Mapped[str] = mapped_column(Text)
    quote_verified: Mapped[bool] = mapped_column(default=False)
    score: Mapped[float] = mapped_column(default=0.0)

    message: Mapped[Message] = relationship(back_populates="citations")
