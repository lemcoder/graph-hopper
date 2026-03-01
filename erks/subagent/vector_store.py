"""FAISS-backed vector store for a single subagent's chunk embeddings."""
from __future__ import annotations

import json
import os
from typing import Optional

import faiss  # type: ignore
import numpy as np

from erks.subagent.ingestion import Chunk


class VectorStore:
    """Stores and retrieves chunk embeddings for one subagent.

    When *subagent_dir* is provided the index and chunk metadata are
    persisted to ``<subagent_dir>/index.faiss`` and
    ``<subagent_dir>/chunks.json`` respectively.  When *subagent_dir* is
    ``None`` the store operates purely in-memory (no disk I/O), which is
    convenient for unit tests.
    """

    _INDEX_FILE = "index.faiss"
    _CHUNKS_FILE = "chunks.json"

    def __init__(self, subagent_dir: Optional[str] = None, dimensions: int = 384):
        self.subagent_dir = subagent_dir
        self.dimensions = dimensions
        self._index: Optional[faiss.IndexFlatIP] = None
        self._chunks: list[Chunk] = []

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, embeddings: list[list[float]], chunks: list[Chunk]) -> None:
        """Normalise vectors, build the FAISS index, and (optionally) persist."""
        if not embeddings:
            return

        vectors = np.array(embeddings, dtype=np.float32)
        self.dimensions = vectors.shape[1]
        faiss.normalize_L2(vectors)

        self._index = faiss.IndexFlatIP(self.dimensions)
        self._index.add(vectors)
        self._chunks = list(chunks)

        if self.subagent_dir:
            os.makedirs(self.subagent_dir, exist_ok=True)
            faiss.write_index(self._index, self._index_path())
            with open(self._chunks_path(), "w", encoding="utf-8") as fh:
                json.dump([c.to_dict() for c in chunks], fh)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load a previously persisted index and chunks from disk."""
        if not self.subagent_dir:
            raise ValueError("Cannot load: subagent_dir is not set")
        self._index = faiss.read_index(self._index_path())
        self.dimensions = self._index.d
        with open(self._chunks_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self._chunks = [Chunk.from_dict(d) for d in data]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query_vector: list[float], k: int = 5) -> list[tuple[Chunk, float]]:
        """Return up to *k* ``(Chunk, cosine_similarity)`` pairs, highest first.

        If fewer than *k* chunks exist all of them are returned.  Ties are
        broken deterministically by ``chunk_index`` ascending.
        """
        if self._index is None or self._index.ntotal == 0:
            return []

        q = np.array([query_vector], dtype=np.float32)
        faiss.normalize_L2(q)

        k_actual = min(k, self._index.ntotal)
        scores, ids = self._index.search(q, k_actual)

        results: list[tuple[Chunk, float]] = []
        for score, idx in zip(scores[0], ids[0]):
            if idx == -1:
                continue
            results.append((self._chunks[int(idx)], float(score)))

        # Deterministic tie-breaking: score desc, chunk_index asc
        results.sort(key=lambda x: (-x[1], x[0].chunk_index))
        return results

    # ------------------------------------------------------------------
    # Drop / delete
    # ------------------------------------------------------------------

    def drop(self) -> None:
        """Clear the in-memory index and delete persisted files (if any)."""
        self._index = None
        self._chunks = []
        if self.subagent_dir:
            for path in (self._index_path(), self._chunks_path()):
                if os.path.exists(path):
                    os.remove(path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _index_path(self) -> str:
        return os.path.join(self.subagent_dir, self._INDEX_FILE)  # type: ignore[arg-type]

    def _chunks_path(self) -> str:
        return os.path.join(self.subagent_dir, self._CHUNKS_FILE)  # type: ignore[arg-type]
