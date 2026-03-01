"""Tests for spec 07 – Retriever."""
from __future__ import annotations

import pytest

from erks.subagent.ingestion import Chunk, DeterministicEmbedder
from erks.subagent.retriever import Retriever
from erks.subagent.vector_store import VectorStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_store(texts: list[str], seed: str = "test") -> tuple[VectorStore, DeterministicEmbedder]:
    emb = DeterministicEmbedder(seed=seed, dim=64)
    chunks = [
        Chunk(text=t, doc_id=f"doc_{i}", chunk_index=i, url_or_path=f"/file_{i}.py")
        for i, t in enumerate(texts)
    ]
    embeddings = emb.embed([c.text for c in chunks])
    vs = VectorStore()
    vs.build(embeddings, chunks)
    return vs, emb


# ---------------------------------------------------------------------------
# retrieve_raw
# ---------------------------------------------------------------------------


def test_retrieve_raw_returns_list_of_chunk_score_tuples():
    vs, emb = _build_store(["alpha beta", "gamma delta", "epsilon zeta"])
    retriever = Retriever(emb, vs)
    results = retriever.retrieve_raw("alpha beta")
    assert all(isinstance(item, tuple) and len(item) == 2 for item in results)
    assert all(isinstance(item[0], Chunk) for item in results)
    assert all(isinstance(item[1], float) for item in results)


def test_retrieve_raw_empty_store_returns_empty():
    vs = VectorStore()
    emb = DeterministicEmbedder(dim=64)
    retriever = Retriever(emb, vs)
    assert retriever.retrieve_raw("anything") == []


def test_retrieve_raw_k_limits_results():
    vs, emb = _build_store(["a", "b", "c", "d", "e", "f"])
    retriever = Retriever(emb, vs)
    results = retriever.retrieve_raw("a", k=3)
    assert len(results) == 3


# ---------------------------------------------------------------------------
# format_context (static)
# ---------------------------------------------------------------------------


def test_format_context_empty_results():
    xml = Retriever.format_context([])
    assert xml == "<context></context>"


def test_format_context_has_correct_tags():
    chunk = Chunk(text="def foo():\n    pass", doc_id="123", chunk_index=0, url_or_path="src/foo.py")
    xml = Retriever.format_context([(chunk, 0.89)])
    assert "<context>" in xml
    assert "</context>" in xml
    assert '<document source="src/foo.py"' in xml
    assert 'doc_id="123"' in xml
    assert 'relevance_score="0.89"' in xml
    assert "<chunk>" in xml
    assert "def foo():" in xml


def test_format_context_multiple_chunks():
    chunks = [
        Chunk(text=f"text {i}", doc_id=f"d{i}", chunk_index=i, url_or_path=f"f{i}.py")
        for i in range(3)
    ]
    results = [(c, float(0.9 - i * 0.1)) for i, c in enumerate(chunks)]
    xml = Retriever.format_context(results)
    assert xml.count("<document") == 3
    assert xml.count("</document>") == 3


# ---------------------------------------------------------------------------
# retrieve_context
# ---------------------------------------------------------------------------


def test_retrieve_context_returns_xml_string():
    vs, emb = _build_store(["hello world", "foo bar"])
    retriever = Retriever(emb, vs)
    ctx = retriever.retrieve_context("hello")
    assert ctx.startswith("<context>")
    assert ctx.endswith("</context>")


def test_retrieve_context_empty_store_returns_empty_context():
    vs = VectorStore()
    emb = DeterministicEmbedder(dim=64)
    retriever = Retriever(emb, vs)
    ctx = retriever.retrieve_context("anything")
    assert ctx == "<context></context>"


def test_retrieve_context_k_fewer_than_total():
    vs, emb = _build_store(["a b", "c d", "e f", "g h", "i j"])
    retriever = Retriever(emb, vs)
    ctx = retriever.retrieve_context("a b", k=2)
    assert ctx.count("<document") == 2


def test_retrieve_context_deterministic():
    """Same query always produces the same XML."""
    vs, emb = _build_store(["foo", "bar", "baz"], seed="s")
    retriever = Retriever(emb, vs)
    ctx1 = retriever.retrieve_context("foo bar", k=3)
    ctx2 = retriever.retrieve_context("foo bar", k=3)
    assert ctx1 == ctx2


def test_retrieve_context_store_with_fewer_than_k_chunks():
    """Should not crash when store has fewer chunks than k."""
    vs, emb = _build_store(["only one chunk"])
    retriever = Retriever(emb, vs)
    ctx = retriever.retrieve_context("query", k=10)
    assert ctx.count("<document") == 1
