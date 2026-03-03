"""Tests for spec 05 – VectorStore (FAISS-backed)."""

from __future__ import annotations

import os

import pytest

from src.subagent.ingestion import Chunk, DeterministicEmbedder
from src.subagent.vector_store import VectorStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunks(n: int) -> list[Chunk]:
    return [
        Chunk(
            text=f"chunk text number {i}",
            doc_id=f"doc_{i}",
            chunk_index=i,
            url_or_path=f"/path/file_{i}.py",
            token_count=4,
        )
        for i in range(n)
    ]


def _make_embeddings(chunks: list[Chunk], seed: str = "test") -> list[list[float]]:
    emb = DeterministicEmbedder(seed=seed, dim=64)
    return emb.embed([c.text for c in chunks])


# ---------------------------------------------------------------------------
# In-memory (no disk) operations
# ---------------------------------------------------------------------------


def test_build_and_search_returns_correct_chunks():
    chunks = _make_chunks(5)
    embeddings = _make_embeddings(chunks)
    vs = VectorStore()
    vs.build(embeddings, chunks)

    query_vec = embeddings[2]  # exact match for chunk 2
    results = vs.search(query_vec, k=1)
    assert len(results) == 1
    chunk, score = results[0]
    assert chunk.chunk_index == 2
    assert score > 0.99  # cosine sim of a vector with itself ≈ 1.0


def test_search_empty_store_returns_empty_list():
    vs = VectorStore()
    result = vs.search([0.1] * 64, k=5)
    assert result == []


def test_search_k_greater_than_total_does_not_crash():
    chunks = _make_chunks(3)
    embeddings = _make_embeddings(chunks)
    vs = VectorStore()
    vs.build(embeddings, chunks)

    results = vs.search(embeddings[0], k=100)
    assert len(results) == 3  # capped at actual count


def test_search_returns_tuples_of_chunk_and_float():
    chunks = _make_chunks(2)
    embeddings = _make_embeddings(chunks)
    vs = VectorStore()
    vs.build(embeddings, chunks)
    results = vs.search(embeddings[0], k=2)
    for item in results:
        assert isinstance(item, tuple)
        assert isinstance(item[0], Chunk)
        assert isinstance(item[1], float)


def test_search_results_sorted_descending_by_score():
    chunks = _make_chunks(5)
    embeddings = _make_embeddings(chunks)
    vs = VectorStore()
    vs.build(embeddings, chunks)
    results = vs.search(embeddings[0], k=5)
    scores = [s for _, s in results]
    assert scores == sorted(scores, reverse=True)


def test_drop_clears_in_memory_index():
    chunks = _make_chunks(3)
    embeddings = _make_embeddings(chunks)
    vs = VectorStore()
    vs.build(embeddings, chunks)
    vs.drop()
    assert vs.search(embeddings[0], k=5) == []


def test_build_empty_embeddings_is_noop():
    vs = VectorStore()
    vs.build([], [])
    assert vs.search([0.0] * 64, k=5) == []


def test_deterministic_search_same_query_same_results():
    chunks = _make_chunks(10)
    embeddings = _make_embeddings(chunks)
    vs = VectorStore()
    vs.build(embeddings, chunks)

    q = DeterministicEmbedder(seed="query", dim=64).embed(["my query"])[0]
    r1 = vs.search(q, k=5)
    r2 = vs.search(q, k=5)
    assert [(c.chunk_index, s) for c, s in r1] == [(c.chunk_index, s) for c, s in r2]


def test_tie_breaking_by_chunk_index():
    """When multiple results have the same score, they are sorted by chunk_index asc."""
    emb = DeterministicEmbedder(seed="same", dim=4)
    # Create two chunks with identical text → identical embeddings → equal cosine sim
    chunks = [
        Chunk(text="identical text", doc_id="d", chunk_index=0),
        Chunk(text="identical text", doc_id="d", chunk_index=1),
    ]
    embeddings = emb.embed([c.text for c in chunks])
    vs = VectorStore()
    vs.build(embeddings, chunks)

    results = vs.search(embeddings[0], k=2)
    assert results[0][0].chunk_index <= results[1][0].chunk_index


# ---------------------------------------------------------------------------
# Disk persistence
# ---------------------------------------------------------------------------


def test_build_creates_index_and_chunks_files(tmp_path):
    chunks = _make_chunks(4)
    embeddings = _make_embeddings(chunks)
    vs = VectorStore(subagent_dir=str(tmp_path))
    vs.build(embeddings, chunks)

    assert os.path.exists(tmp_path / "index.faiss")
    assert os.path.exists(tmp_path / "chunks.json")


def test_load_and_search_after_persist(tmp_path):
    chunks = _make_chunks(4)
    embeddings = _make_embeddings(chunks)

    # Build & persist
    vs1 = VectorStore(subagent_dir=str(tmp_path))
    vs1.build(embeddings, chunks)

    # Load into fresh instance
    vs2 = VectorStore(subagent_dir=str(tmp_path))
    vs2.load()

    results = vs2.search(embeddings[1], k=1)
    assert len(results) == 1
    assert results[0][0].chunk_index == 1


def test_drop_removes_disk_files(tmp_path):
    chunks = _make_chunks(2)
    embeddings = _make_embeddings(chunks)
    vs = VectorStore(subagent_dir=str(tmp_path))
    vs.build(embeddings, chunks)
    vs.drop()

    assert not os.path.exists(tmp_path / "index.faiss")
    assert not os.path.exists(tmp_path / "chunks.json")
    assert vs.search(embeddings[0], k=5) == []


def test_drop_without_dir_is_safe():
    vs = VectorStore()
    chunks = _make_chunks(2)
    vs.build(_make_embeddings(chunks), chunks)
    vs.drop()  # should not raise


def test_load_without_subagent_dir_raises():
    vs = VectorStore()
    with pytest.raises(ValueError, match="subagent_dir"):
        vs.load()


def test_rebuild_overwrites_previous_index(tmp_path):
    """Re-building the store replaces old data."""
    chunks_v1 = _make_chunks(2)
    embs_v1 = _make_embeddings(chunks_v1, seed="v1")
    vs = VectorStore(subagent_dir=str(tmp_path))
    vs.build(embs_v1, chunks_v1)

    chunks_v2 = _make_chunks(4)
    embs_v2 = _make_embeddings(chunks_v2, seed="v2")
    vs.build(embs_v2, chunks_v2)

    results = vs.search(embs_v2[0], k=10)
    assert len(results) == 4
