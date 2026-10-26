"""Provider interfaces. Adapters translate vendor errors into :class:`ProviderError` without leaking secrets."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np


class EmbeddingProvider(ABC):
    #: stable identifier stored with each document so a model change is detected
    model_id: str
    dim: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Return L2-normalised float32 array of shape (len(texts), dim)."""

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray:
        """Return L2-normalised float32 vector of shape (dim,)."""

    def check_ready(self) -> None:
        """Raise ProviderError if the provider cannot be used. Must not download models."""


@dataclass
class LLMMessage:
    role: str  # "user" | "assistant"
    content: str


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def generate_structured(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        schema: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Return a JSON object (best effort conforming to ``schema``). Callers validate the result."""

    def check_ready(self) -> None:
        """Raise ProviderNotConfigured if credentials are missing."""


def normalise(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms
