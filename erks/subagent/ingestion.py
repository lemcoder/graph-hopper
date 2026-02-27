"""Ingestion pipeline and embedding stubs."""
from __future__ import annotations

import hashlib
import struct
from typing import Protocol


class EmbeddingInterface(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class DeterministicEmbedder:
    """SHA-256 based deterministic embedder for tests. seed is optional."""

    def __init__(self, seed: str = "", dim: int = 64):
        self.seed = seed
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        raw = hashlib.sha256((self.seed + text).encode()).digest()
        floats: list[float] = []
        chunk = raw
        while len(floats) < self.dim:
            for i in range(0, len(chunk) - 3, 4):
                val = struct.unpack_from("f", chunk, i)[0]
                if val == val:  # not NaN
                    floats.append(val)
            # Extend by hashing the previous chunk to get more floats
            chunk = hashlib.sha256(chunk).digest()
        floats = floats[: self.dim]
        magnitude = sum(f * f for f in floats) ** 0.5
        if magnitude > 0:
            floats = [f / magnitude for f in floats]
        return floats


class Chunk:
    def __init__(
        self,
        text: str,
        doc_id: str,
        chunk_index: int,
        url_or_path: str = "",
        token_count: int = 0,
        metadata: dict | None = None,
    ):
        self.text = text
        self.doc_id = doc_id
        self.chunk_index = chunk_index
        self.url_or_path = url_or_path
        self.token_count = token_count
        self.metadata = metadata or {}


class IngestionResult:
    def __init__(self, chunks: list[Chunk], embeddings: list[list[float]]):
        self.chunks = chunks
        self.embeddings = embeddings


class IngestionPipeline:
    """Performs the ingestion pipeline: fetch -> extract -> chunk -> embed."""

    def __init__(self, embedder: EmbeddingInterface):
        self.embedder = embedder

    async def ingest(self, source_config) -> IngestionResult:
        chunks = [
            Chunk(
                text=f"Source: {source_config.location}",
                doc_id="doc_0",
                chunk_index=0,
                url_or_path=source_config.location,
                token_count=10,
            )
        ]
        embeddings = self.embedder.embed([c.text for c in chunks])
        return IngestionResult(chunks=chunks, embeddings=embeddings)
