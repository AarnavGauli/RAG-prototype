"""FAISS-backed vector store persisted to disk. SQLite is the source of truth; this index is rebuildable."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

import faiss
import numpy as np

log = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.index_path = directory / "index.faiss"
        self._lock = threading.RLock()
        self._index: faiss.IndexIDMap2 | None = None
        self._load()

    # ---- persistence -------------------------------------------------------------------
    def _load(self) -> None:
        if self.index_path.exists():
            try:
                self._index = faiss.read_index(str(self.index_path))
            except Exception:
                log.warning("Vector index unreadable; it will be rebuilt from the database")
                self._index = None

    def _save(self) -> None:
        if self._index is None:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        faiss.write_index(self._index, str(tmp))
        os.replace(tmp, self.index_path)

    def _ensure(self, dim: int) -> faiss.IndexIDMap2:
        if self._index is not None and self._index.d != dim:
            log.warning("Embedding dimension changed (%s -> %s); resetting vector index", self._index.d, dim)
            self._index = None
        if self._index is None:
            self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
        return self._index

    # ---- operations --------------------------------------------------------------------
    @property
    def count(self) -> int:
        with self._lock:
            return 0 if self._index is None else int(self._index.ntotal)

    def ids(self) -> set[int]:
        with self._lock:
            if self._index is None or self._index.ntotal == 0:
                return set()
            return {int(i) for i in faiss.vector_to_array(self._index.id_map)}

    def add(self, ids: list[int], vectors: np.ndarray) -> None:
        if not ids:
            return
        with self._lock:
            index = self._ensure(vectors.shape[1])
            arr = np.ascontiguousarray(vectors, dtype=np.float32)
            id_arr = np.asarray(ids, dtype=np.int64)
            index.remove_ids(id_arr)  # idempotent re-adds
            index.add_with_ids(arr, id_arr)
            self._save()

    def remove(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            if self._index is None:
                return
            self._index.remove_ids(np.asarray(ids, dtype=np.int64))
            self._save()

    def search(self, query: np.ndarray, k: int, allowed_ids: set[int]) -> list[tuple[int, float]]:
        """Top-k (id, cosine score) restricted to ``allowed_ids``."""
        if not allowed_ids:
            return []
        with self._lock:
            if self._index is None or self._index.ntotal == 0 or query.shape[-1] != self._index.d:
                return []
            selector = faiss.IDSelectorBatch(np.asarray(sorted(allowed_ids), dtype=np.int64))
            params = faiss.SearchParameters(sel=selector)
            q = np.ascontiguousarray(query.reshape(1, -1), dtype=np.float32)
            scores, ids = self._index.search(q, k, params=params)
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0], strict=True) if i != -1]

    def reconcile(self, expected: dict[int, bytes], dim_hint: int | None = None) -> tuple[int, int]:
        """Make the index contain exactly ``expected`` (id -> float32 bytes). Returns (added, removed)."""
        with self._lock:
            present = self.ids()
            stale = sorted(present - expected.keys())
            missing = sorted(expected.keys() - present)
            if stale:
                self.remove(stale)
            if missing:
                vecs = np.stack([np.frombuffer(expected[i], dtype=np.float32) for i in missing])
                self.add(missing, vecs)
            return len(missing), len(stale)

    def reset(self) -> None:
        with self._lock:
            self._index = None
            self.index_path.unlink(missing_ok=True)


def write_meta(directory: Path, model_id: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "meta.json").write_text(json.dumps({"embedding_model": model_id}))
