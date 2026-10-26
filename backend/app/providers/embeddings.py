"""Embedding providers: offline hashing, local ONNX (fastembed), OpenAI-compatible HTTP."""

from __future__ import annotations

import hashlib
import itertools
import logging
import re
import threading

import httpx
import numpy as np

from app.config import Settings
from app.errors import ProviderError, ProviderNotConfigured
from app.providers.base import EmbeddingProvider, normalise

log = logging.getLogger(__name__)
_WORD = re.compile(r"[\w]+", re.UNICODE)


class HashEmbedding(EmbeddingProvider):
    """Deterministic feature-hashing embedding (unigrams + bigrams, sublinear tf).

    It needs no model download and no network, so it is used for tests, CI and offline evaluation.
    It captures lexical overlap only - it is a real vector search, but much weaker than a trained model.
    """

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.model_id = f"hash-{dim}"

    def _vec(self, text: str) -> np.ndarray:
        words = [w.lower() for w in _WORD.findall(text)]
        counts: dict[str, int] = {}
        for tok in words + [f"{a}_{b}" for a, b in itertools.pairwise(words)]:
            counts[tok] = counts.get(tok, 0) + 1
        v = np.zeros(self.dim, dtype=np.float32)
        for tok, c in counts.items():
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
            sign = 1.0 if (h >> 63) & 1 else -1.0
            v[h % self.dim] += sign * (1.0 + np.log(c))
        return v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return normalise(np.stack([self._vec(t) for t in texts])) if texts else np.zeros((0, self.dim), "float32")

    def embed_query(self, text: str) -> np.ndarray:
        return normalise(self._vec(text)[None, :])[0]


class FastEmbedEmbedding(EmbeddingProvider):
    """Local ONNX embeddings via fastembed. The model is downloaded once, on first use (~70 MB for bge-small)."""

    def __init__(self, model_name: str, cache_dir: str, batch_size: int) -> None:
        self.model_name = model_name
        self.model_id = f"fastembed:{model_name}"
        self.cache_dir = cache_dir
        self.batch_size = batch_size
        self._model = None
        self._lock = threading.Lock()
        self.dim = 0

    def _load(self):
        with self._lock:
            if self._model is None:
                try:
                    from fastembed import TextEmbedding

                    log.info("Loading embedding model %s (downloads on first use)", self.model_name)
                    self._model = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)
                    self.dim = len(next(iter(self._model.embed(["dimension probe"]))))
                except Exception as exc:
                    raise ProviderError(
                        f"Could not load local embedding model '{self.model_name}'. The first run needs "
                        "network access to download it; alternatively set PDFI_EMBEDDING_PROVIDER=hash "
                        f"for offline (lower quality) search. ({type(exc).__name__})",
                        code="embedding_unavailable",
                        status_code=503,
                    ) from exc
            return self._model

    def check_ready(self) -> None:
        self._load()

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        if not texts:
            return np.zeros((0, self.dim), "float32")
        return normalise(np.array(list(model.embed(texts, batch_size=self.batch_size)), dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        model = self._load()
        fn = getattr(model, "query_embed", None)
        vec = next(iter(fn(text) if fn else model.embed([text])))
        return normalise(np.asarray(vec, dtype=np.float32)[None, :])[0]


class OpenAIEmbedding(EmbeddingProvider):
    """OpenAI-compatible ``/embeddings`` endpoint."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.embedding_base_url.rstrip("/")
        self.model = settings.embedding_model
        self.model_id = f"openai:{self.model}"
        self._key = settings.embedding_api_key
        self.batch_size = settings.embedding_batch_size
        self.timeout = settings.llm_timeout_seconds
        self.dim = 0

    def check_ready(self) -> None:
        if self._key is None or not self._key.get_secret_value():
            raise ProviderNotConfigured(
                "Embedding API key is not set. Set PDFI_EMBEDDING_API_KEY, or use PDFI_EMBEDDING_PROVIDER=fastembed.",
                code="embedding_not_configured",
            )

    def _post(self, inputs: list[str]) -> np.ndarray:
        self.check_ready()
        assert self._key is not None
        try:
            r = httpx.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._key.get_secret_value()}"},
                json={"model": self.model, "input": inputs},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Could not reach the embedding service ({type(exc).__name__}).",
                code="embedding_unavailable",
                status_code=503,
            ) from exc
        if r.status_code in (401, 403):
            raise ProviderError("The embedding service rejected the API key.", code="embedding_auth_failed")
        if r.status_code == 429:
            raise ProviderError(
                "The embedding service is rate limiting requests.", code="embedding_rate_limited", status_code=503
            )
        if r.status_code >= 400:
            raise ProviderError(f"The embedding service returned HTTP {r.status_code}.", code="embedding_failed")
        try:
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            arr = np.array([d["embedding"] for d in data], dtype=np.float32)
        except Exception as exc:
            raise ProviderError("Unexpected response from the embedding service.", code="embedding_failed") from exc
        self.dim = arr.shape[1]
        return normalise(arr)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), "float32")
        parts = [self._post(texts[i : i + self.batch_size]) for i in range(0, len(texts), self.batch_size)]
        return np.vstack(parts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._post([text])[0]


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "hash":
        return HashEmbedding()
    if settings.embedding_provider == "openai":
        return OpenAIEmbedding(settings)
    assert settings.embedding_cache_dir is not None
    return FastEmbedEmbedding(
        settings.embedding_model, str(settings.embedding_cache_dir), settings.embedding_batch_size
    )
