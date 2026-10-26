"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorInfo


class Progress(BaseModel):
    current: int
    total: int


class DocumentError(BaseModel):
    code: str
    message: str
    retryable: bool


class DocumentOut(BaseModel):
    id: str
    name: str
    size_bytes: int
    page_count: int
    chunk_count: int
    status: Literal["queued", "processing", "ready", "failed"]
    stage: str | None
    progress: Progress | None
    error: DocumentError | None
    created_at: datetime
    updated_at: datetime


class ConversationCreate(BaseModel):
    title: str | None = Field(None, max_length=200)
    document_ids: list[str] = Field(default_factory=list, max_length=100)


class ConversationUpdate(BaseModel):
    title: str | None = Field(None, max_length=200)
    document_ids: list[str] | None = Field(None, max_length=100)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("title must not be empty")
        return v


class ConversationOut(BaseModel):
    id: str
    title: str
    document_ids: list[str]
    created_at: datetime
    updated_at: datetime


class QuestionIn(BaseModel):
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be blank")
        return v


class CitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str
    document_id: str
    document_name: str
    page_number: int
    excerpt: str
    quote_verified: bool
    score: float


class MessageMeta(BaseModel):
    retrieved: int | None = None
    top_score: float | None = None
    reason: str | None = None


class MessageOut(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    status: Literal["ok", "insufficient_evidence"]
    created_at: datetime
    citations: list[CitationOut]
    meta: MessageMeta | None = None


class MessagePage(BaseModel):
    messages: list[MessageOut]
    has_more: bool


class AnswerOut(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut


class CitationDetail(CitationOut):
    chunk_text: str
    char_start: int
    char_end: int
    page_image_url: str
    message_id: str


class ProviderStatus(BaseModel):
    provider: str
    model: str
    ready: bool
    detail: str | None = None


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: bool
    indexed_chunks: int
    embedding: ProviderStatus
    llm: ProviderStatus
    limits: dict[str, int]
