from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.context import build_context
from app.errors import ProviderError
from app.main import create_app
from app.providers.base import LLMMessage, LLMProvider
from app.providers.embeddings import HashEmbedding

PAGES = [
    "The Aurora telescope array has 48 dishes spread across the high desert. Its primary mission is mapping hydrogen clouds.",
    "Operating budget. The annual operating budget is 12 million euros, funded mostly by the national science council.",
    "Staffing. The observatory employs 31 engineers and 9 astronomers. Night shifts rotate every two weeks.",
]


def make_pdf(pages: list[str] | None = None, *, encrypt: bool = False, blank_pages: set[int] | None = None) -> bytes:
    doc = pymupdf.open()
    for i, text in enumerate(pages if pages is not None else PAGES):
        page = doc.new_page()
        if text and i not in (blank_pages or set()):
            page.insert_textbox(pymupdf.Rect(60, 60, 540, 780), text, fontsize=12)
    kwargs = {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "user_pw": "secret", "owner_pw": "owner"} if encrypt else {}
    return doc.tobytes(**kwargs)


def make_image_only_pdf() -> bytes:
    """A 'scanned' PDF: a page that holds a drawn shape and no text layer."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(100, 100, 300, 300), fill=(0, 0, 0))
    return doc.tobytes()


class ScriptedLLM(LLMProvider):
    """Test double. ``responder(messages)`` returns the structured dict the 'model' answers with."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self) -> None:
        self.calls: list[list[LLMMessage]] = []
        self.responder: Callable[[list[LLMMessage]], dict[str, Any]] = lambda m: {
            "sufficient_evidence": True,
            "answer": "The array has 48 dishes [S1].",
            "citations": [{"source": "S1", "quote": "48 dishes"}],
        }
        self.error: Exception | None = None
        self.system_prompts: list[str] = []

    def generate_structured(self, *, system, messages, schema, max_tokens):
        self.calls.append(messages)
        self.system_prompts.append(system)
        if self.error:
            raise self.error
        return self.responder(messages)


class FlakyEmbedder(HashEmbedding):
    def __init__(self) -> None:
        super().__init__()
        self.failures = 0

    def embed_documents(self, texts):
        if self.failures > 0:
            self.failures -= 1
            raise ProviderError("embedding service down", code="embedding_unavailable", status_code=503)
        return super().embed_documents(texts)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        embedding_provider="hash",
        chunk_size_tokens=60,
        chunk_overlap_tokens=10,
        rate_limit_per_minute=0,
        cors_origins=["http://localhost:3000"],
        environment="test",
    )


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def embedder() -> FlakyEmbedder:
    return FlakyEmbedder()


@pytest.fixture
def ctx(settings: Settings, llm: ScriptedLLM, embedder: FlakyEmbedder):
    from app.db import Base

    context = build_context(settings, embedder=embedder, llm=llm)
    Base.metadata.create_all(context.engine)
    return context


@pytest.fixture
def client(ctx) -> Iterator[TestClient]:
    app = create_app(ctx=ctx, migrate=False)
    with TestClient(app, base_url="http://localhost") as c:
        yield c


def wait_for(client: TestClient, doc_id: str, status: str = "ready", timeout: float = 15) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        doc = client.get(f"/api/v1/documents/{doc_id}").json()
        if doc["status"] == status:
            return doc
        if doc["status"] == "failed" and status != "failed":
            raise AssertionError(f"document failed: {doc['error']}")
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {status}: {doc}")


def upload(client: TestClient, data: bytes | None = None, name: str = "report.pdf", wait: bool = True) -> dict:
    r = client.post(
        "/api/v1/documents", files={"file": (name, data if data is not None else make_pdf(), "application/pdf")}
    )
    assert r.status_code == 202, r.text
    doc = r.json()
    return wait_for(client, doc["id"]) if wait else doc


@pytest.fixture
def uploaded(client: TestClient) -> dict:
    return upload(client)


def new_conversation(client: TestClient, **body: Any) -> dict:
    r = client.post("/api/v1/conversations", json=body)
    assert r.status_code == 201, r.text
    return r.json()
