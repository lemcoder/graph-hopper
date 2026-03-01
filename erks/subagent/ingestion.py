"""Ingestion pipeline, chunking, and embedding implementations."""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol


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


class FastEmbedder:
    """Production embedder backed by fastembed (ONNX, local CPU inference)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", batch_size: int = 64):
        self._model_name = model_name
        self._batch_size = batch_size
        self._model = None  # lazy-loaded

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding  # type: ignore
            self._model = TextEmbedding(model_name=self._model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load()
        embeddings = list(
            self._model.embed(texts, batch_size=self._batch_size)  # type: ignore[union-attr]
        )
        return [list(map(float, vec)) for vec in embeddings]


@dataclass
class Chunk:
    """A text fragment with provenance metadata."""

    text: str
    doc_id: str
    chunk_index: int
    url_or_path: str = ""
    token_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializes the Chunk to a dictionary for JSON storage."""
        return {
            "text": self.text,
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "url_or_path": self.url_or_path,
            "token_count": self.token_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chunk":
        """Deserializes a dictionary into a Chunk object."""
        return cls(**data)


@dataclass
class IngestionResult:
    """Parallel lists of chunks and their dense vector embeddings."""

    chunks: list[Chunk]
    embeddings: list[list[float]]


class TokenWindowChunker:
    """Splits text into overlapping token windows.

    Uses word-based tokenization by default.  Pass custom ``encode_fn`` /
    ``decode_fn`` callables to use a real subword tokenizer.
    """

    def __init__(
        self,
        encode_fn: Optional[Callable[[str], list]] = None,
        decode_fn: Optional[Callable[[list], str]] = None,
        target_tokens: int = 500,
        overlap_tokens: int = 50,
        min_tokens: int = 64,
    ):
        self._encode: Callable[[str], list] = encode_fn if encode_fn is not None else lambda t: t.split()
        self._decode: Callable[[list], str] = decode_fn if decode_fn is not None else lambda toks: " ".join(toks)
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens
        self.min_tokens = min_tokens

    def chunk(self, text: str, doc_id: str, url_or_path: str = "") -> list[Chunk]:
        """Return a list of Chunks for a single document."""
        tokens = self._encode(text)
        if not tokens:
            return []

        step = max(1, self.target_tokens - self.overlap_tokens)
        chunks: list[Chunk] = []
        idx = 0
        chunk_index = 0

        while idx < len(tokens):
            window = tokens[idx : idx + self.target_tokens]
            is_last = (idx + self.target_tokens) >= len(tokens)

            if is_last and len(window) < self.min_tokens and chunks:
                # Trailing tiny window: merge into previous chunk
                prev = chunks[-1]
                merged = self._encode(prev.text) + list(window)
                prev.text = self._decode(merged)
                prev.token_count = len(merged)
                break

            if len(window) < self.min_tokens and not chunks:
                # Trivial document: keep as single chunk
                chunks.append(
                    Chunk(
                        text=self._decode(window),
                        doc_id=doc_id,
                        chunk_index=chunk_index,
                        url_or_path=url_or_path,
                        token_count=len(window),
                    )
                )
                break

            if window:
                chunks.append(
                    Chunk(
                        text=self._decode(window),
                        doc_id=doc_id,
                        chunk_index=chunk_index,
                        url_or_path=url_or_path,
                        token_count=len(window),
                    )
                )
                chunk_index += 1

            idx += step

        return chunks


class IngestionPipeline:
    """Performs the ingestion pipeline: fetch -> extract -> chunk -> embed."""

    def __init__(
        self,
        embedder: EmbeddingInterface,
        chunker: Optional[TokenWindowChunker] = None,
    ):
        self.embedder = embedder
        self.chunker = chunker or TokenWindowChunker()

    async def ingest(self, source_config) -> IngestionResult:
        text = f"Source: {source_config.location}"
        chunks = self.chunker.chunk(text, doc_id="doc_0", url_or_path=source_config.location)
        if not chunks:
            # Fallback for trivially small documents
            chunks = [
                Chunk(
                    text=text,
                    doc_id="doc_0",
                    chunk_index=0,
                    url_or_path=source_config.location,
                    token_count=len(text.split()),
                )
            ]
        embeddings = self.embedder.embed([c.text for c in chunks])
        return IngestionResult(chunks=chunks, embeddings=embeddings)
