"""Tests for spec 04 – token-window chunking and embedding."""

from __future__ import annotations

import pytest

from erks.subagent.ingestion import (
    Chunk,
    DeterministicEmbedder,
    IngestionPipeline,
    IngestionResult,
    TokenWindowChunker,
)


# ---------------------------------------------------------------------------
# Chunk serialisation
# ---------------------------------------------------------------------------


def test_chunk_to_dict_and_from_dict_round_trip():
    chunk = Chunk(
        text="hello world",
        doc_id="doc_1",
        chunk_index=3,
        url_or_path="/path/to/file.py",
        token_count=2,
        metadata={"lang": "en"},
    )
    d = chunk.to_dict()
    assert d["text"] == "hello world"
    assert d["chunk_index"] == 3
    assert d["metadata"] == {"lang": "en"}

    restored = Chunk.from_dict(d)
    assert restored.text == chunk.text
    assert restored.doc_id == chunk.doc_id
    assert restored.chunk_index == chunk.chunk_index
    assert restored.url_or_path == chunk.url_or_path
    assert restored.token_count == chunk.token_count
    assert restored.metadata == chunk.metadata


def test_chunk_default_metadata_is_empty_dict():
    chunk = Chunk(text="x", doc_id="d", chunk_index=0)
    assert chunk.metadata == {}


def test_chunk_from_dict_no_metadata():
    d = {
        "text": "hi",
        "doc_id": "d",
        "chunk_index": 0,
        "url_or_path": "",
        "token_count": 1,
        "metadata": {},
    }
    chunk = Chunk.from_dict(d)
    assert chunk.metadata == {}


# ---------------------------------------------------------------------------
# IngestionResult is a dataclass
# ---------------------------------------------------------------------------


def test_ingestion_result_fields():
    chunks = [Chunk(text="t", doc_id="d", chunk_index=0)]
    embeddings = [[0.1, 0.2]]
    result = IngestionResult(chunks=chunks, embeddings=embeddings)
    assert result.chunks is chunks
    assert result.embeddings is embeddings


# ---------------------------------------------------------------------------
# DeterministicEmbedder
# ---------------------------------------------------------------------------


def test_deterministic_embedder_stability():
    emb = DeterministicEmbedder(seed="s", dim=32)
    v1 = emb.embed(["hello"])
    v2 = emb.embed(["hello"])
    assert v1 == v2


def test_deterministic_embedder_different_texts_differ():
    emb = DeterministicEmbedder(seed="", dim=32)
    v1 = emb.embed(["hello"])[0]
    v2 = emb.embed(["world"])[0]
    assert v1 != v2


def test_deterministic_embedder_unit_vector():
    emb = DeterministicEmbedder(seed="test", dim=64)
    v = emb.embed(["sample text"])[0]
    magnitude = sum(f * f for f in v) ** 0.5
    assert abs(magnitude - 1.0) < 1e-5


def test_deterministic_embedder_correct_dimension():
    emb = DeterministicEmbedder(dim=128)
    v = emb.embed(["abc"])[0]
    assert len(v) == 128


# ---------------------------------------------------------------------------
# TokenWindowChunker
# ---------------------------------------------------------------------------


def _make_text(n_words: int) -> str:
    return " ".join(f"word{i}" for i in range(n_words))


def test_chunker_empty_text_returns_no_chunks():
    chunker = TokenWindowChunker(target_tokens=10, overlap_tokens=2, min_tokens=4)
    assert chunker.chunk("", doc_id="d") == []


def test_chunker_trivial_document_below_min_kept_as_single_chunk():
    """A document with fewer tokens than min_tokens should be kept (not discarded)."""
    chunker = TokenWindowChunker(target_tokens=500, overlap_tokens=50, min_tokens=64)
    text = "short text"  # 2 words << 64
    chunks = chunker.chunk(text, doc_id="d")
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].chunk_index == 0


def test_chunker_single_window():
    """Text that fits in one window produces a single chunk."""
    chunker = TokenWindowChunker(target_tokens=10, overlap_tokens=2, min_tokens=3)
    text = _make_text(8)  # 8 words
    chunks = chunker.chunk(text, doc_id="d")
    assert len(chunks) == 1
    assert chunks[0].token_count == 8


def test_chunker_multiple_windows():
    """Text longer than target_tokens produces multiple chunks."""
    chunker = TokenWindowChunker(target_tokens=5, overlap_tokens=1, min_tokens=2)
    text = _make_text(12)
    chunks = chunker.chunk(text, doc_id="d")
    assert len(chunks) > 1


def test_chunker_chunk_indices_are_sequential():
    chunker = TokenWindowChunker(target_tokens=4, overlap_tokens=1, min_tokens=2)
    text = _make_text(20)
    chunks = chunker.chunk(text, doc_id="d")
    for i, c in enumerate(chunks):
        assert c.chunk_index == i


def test_chunker_overlap_means_shared_tokens():
    """Consecutive chunks share `overlap` tokens at their boundary."""
    chunker = TokenWindowChunker(target_tokens=5, overlap_tokens=2, min_tokens=1)
    text = _make_text(10)
    chunks = chunker.chunk(text, doc_id="d")
    if len(chunks) >= 2:
        tokens_0 = chunks[0].text.split()
        tokens_1 = chunks[1].text.split()
        overlap = set(tokens_0[-2:]) & set(tokens_1[:2])
        assert len(overlap) > 0


def test_chunker_trailing_tiny_chunk_merged_into_previous():
    """If the last chunk is < min_tokens, it is merged into the previous one."""
    chunker = TokenWindowChunker(target_tokens=6, overlap_tokens=1, min_tokens=3)
    # 7 words: first window = 6 words, step = 5, second window starts at 5 → only 2 words (< 3)
    text = _make_text(7)
    chunks = chunker.chunk(text, doc_id="d")
    # Should be 1 chunk (tiny remainder merged into first)
    assert len(chunks) == 1
    # The merged chunk must contain all original words (overlap may cause some to repeat)
    for i in range(7):
        assert f"word{i}" in chunks[0].text


def test_chunker_doc_id_and_url_propagated():
    chunker = TokenWindowChunker(target_tokens=10, overlap_tokens=2, min_tokens=2)
    text = _make_text(5)
    chunks = chunker.chunk(text, doc_id="my_doc", url_or_path="/some/path.py")
    for c in chunks:
        assert c.doc_id == "my_doc"
        assert c.url_or_path == "/some/path.py"


def test_chunker_custom_encode_decode():
    """Custom encode/decode callables are used if provided."""
    # Token = single character
    encode = list
    decode = "".join
    chunker = TokenWindowChunker(
        encode_fn=encode,
        decode_fn=decode,
        target_tokens=4,
        overlap_tokens=1,
        min_tokens=2,
    )
    text = "abcdefgh"  # 8 chars
    chunks = chunker.chunk(text, doc_id="d")
    assert len(chunks) > 0
    reassembled = "".join(c.text for c in chunks)
    # All characters should appear in the reassembled output (some may repeat due to overlap)
    for ch in text:
        assert ch in reassembled


# ---------------------------------------------------------------------------
# IngestionPipeline integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_returns_ingestion_result():
    from erks.models import SourceConfig, SourceType

    pipeline = IngestionPipeline(DeterministicEmbedder(seed="t", dim=16))
    cfg = SourceConfig(
        type=SourceType.GIT, location="https://github.com/example/repo.git"
    )
    result = await pipeline.ingest(cfg)
    assert isinstance(result, IngestionResult)
    assert len(result.chunks) > 0
    assert len(result.embeddings) == len(result.chunks)


@pytest.mark.asyncio
async def test_pipeline_chunks_and_embeddings_are_parallel():
    from erks.models import SourceConfig, SourceType

    pipeline = IngestionPipeline(DeterministicEmbedder(dim=8))
    cfg = SourceConfig(type=SourceType.HTTP, location="https://example.com/")
    result = await pipeline.ingest(cfg)
    assert len(result.chunks) == len(result.embeddings)
    for emb in result.embeddings:
        assert len(emb) == 8
