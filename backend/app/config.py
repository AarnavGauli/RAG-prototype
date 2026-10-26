"""Application settings, loaded from environment variables (prefix ``PDFI_``) and an optional ``.env`` file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EmbeddingProviderName = Literal["fastembed", "hash", "openai"]
LLMProviderName = Literal["anthropic", "openai", "gemini"]

# Cosine-similarity floors below which a passage is not considered relevant evidence.
# They depend on the embedding model and should be re-calibrated with the evaluation suite. bge-small cosines are
# compressed (unrelated text still scores ~0.4-0.55), so the LLM's own sufficiency judgement is a second gate.
DEFAULT_MIN_SCORE = {"fastembed": 0.5, "hash": 0.12, "openai": 0.30}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PDFI_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- storage -------------------------------------------------------------------------
    data_dir: Path = Path("./data")
    database_url: str | None = None  # default: sqlite:///<data_dir>/pdf_intelligence.db
    upload_dir: Path | None = None  # default: <data_dir>/uploads
    vector_dir: Path | None = None  # default: <data_dir>/vectors

    # --- limits --------------------------------------------------------------------------
    max_upload_mb: int = Field(20, ge=1, le=500)
    max_documents: int = Field(25, ge=1)
    max_pages: int = Field(500, ge=1)
    max_question_chars: int = Field(2000, ge=10, le=20000)
    max_json_body_kb: int = Field(64, ge=1)
    rate_limit_per_minute: int = Field(60, ge=0)  # per owner, expensive endpoints; 0 disables

    # --- chunking (estimated tokens; see services/chunking.py) -----------------------------
    chunk_size_tokens: int = Field(350, ge=50, le=2000)
    chunk_overlap_tokens: int = Field(60, ge=0)

    # --- retrieval -----------------------------------------------------------------------
    retrieval_top_k: int = Field(6, ge=1)
    retrieval_max_top_k: int = Field(20, ge=1)
    retrieval_min_score: float | None = Field(None, ge=-1, le=1)
    retrieval_dedupe_similarity: float = Field(0.85, ge=0, le=1)
    context_max_tokens: int = Field(3500, ge=200)
    history_max_turns: int = Field(3, ge=0, le=10)

    # --- embeddings ----------------------------------------------------------------------
    embedding_provider: EmbeddingProviderName = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_batch_size: int = Field(32, ge=1)
    embedding_base_url: str = "https://api.openai.com/v1"  # for provider=openai
    embedding_api_key: SecretStr | None = None
    embedding_cache_dir: Path | None = None  # fastembed model cache; default: <data_dir>/models

    # --- LLM -----------------------------------------------------------------------------
    llm_provider: LLMProviderName = "anthropic"
    llm_model: str | None = None  # provider default if unset
    llm_base_url: str = "https://api.openai.com/v1"  # for provider=openai (also Ollama, vLLM, ...)
    llm_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = Field(None, validation_alias="GEMINI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(None, validation_alias="ANTHROPIC_API_KEY")
    llm_max_output_tokens: int = Field(1200, ge=100)
    llm_timeout_seconds: float = Field(60, gt=0)

    # --- web -----------------------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:3000"]
    cookie_secure: bool = False  # set true when served over HTTPS
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _derive(self) -> Settings:
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")
        if self.retrieval_top_k > self.retrieval_max_top_k:
            raise ValueError("retrieval_top_k must not exceed retrieval_max_top_k")
        self.data_dir = self.data_dir.expanduser().resolve()
        if self.upload_dir is None:
            self.upload_dir = self.data_dir / "uploads"
        if self.vector_dir is None:
            self.vector_dir = self.data_dir / "vectors"
        if self.embedding_cache_dir is None:
            self.embedding_cache_dir = self.data_dir / "models"
        if self.database_url is None:
            self.database_url = f"sqlite:///{self.data_dir / 'pdf_intelligence.db'}"
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def min_score(self) -> float:
        if self.retrieval_min_score is not None:
            return self.retrieval_min_score
        return DEFAULT_MIN_SCORE[self.embedding_provider]

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.upload_dir, self.vector_dir):
            assert p is not None
            p.mkdir(parents=True, exist_ok=True)


def load_settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]
