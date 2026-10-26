"""Application context: wires settings, database, vector store and providers together."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import make_engine, make_session_factory
from app.providers.base import EmbeddingProvider, LLMProvider
from app.providers.embeddings import build_embedding_provider
from app.providers.llm import build_llm_provider
from app.services.vectorstore import VectorStore


@dataclass
class AppContext:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    vectors: VectorStore
    embedder: EmbeddingProvider
    llm: LLMProvider
    executor: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=1, thread_name_prefix="indexer")
    )
    lock: threading.Lock = field(default_factory=threading.Lock)

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)
        self.engine.dispose()


def build_context(
    settings: Settings,
    *,
    embedder: EmbeddingProvider | None = None,
    llm: LLMProvider | None = None,
) -> AppContext:
    settings.ensure_dirs()
    engine = make_engine(settings.database_url or "")
    assert settings.vector_dir is not None
    return AppContext(
        settings=settings,
        engine=engine,
        session_factory=make_session_factory(engine),
        vectors=VectorStore(settings.vector_dir),
        embedder=embedder or build_embedding_provider(settings),
        llm=llm or build_llm_provider(settings),
    )
