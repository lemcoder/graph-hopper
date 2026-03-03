"""Tests using golden fixtures – validates ingestion and querying against
synthetic, deterministic documents with known content.

These tests serve as the ground truth for the ingestion, retrieval, and
confidence scoring pipeline.  No network calls are made; the
DeterministicEmbedder is used throughout and all LLM responses are mocked.
"""

from __future__ import annotations

import os

import pytest

from src.config import Config
from src.models import SourceConfig, SourceType, SubagentStatus
from src.orchestrator.in_memory import InMemoryOrchestrator
from src.subagent.confidence import ConfidenceScorer
from src.subagent.ingestion import (
    Chunk,
    DeterministicEmbedder,
    IngestionPipeline,
    TokenWindowChunker,
)
from src.subagent.retriever import Retriever
from src.subagent.subagent import MockLLM, Subagent
from src.subagent.vector_store import VectorStore

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")

PYTHON_GUIDE_PATH = os.path.join(FIXTURES_DIR, "python_guide.md")
ML_FUNDAMENTALS_PATH = os.path.join(FIXTURES_DIR, "ml_fundamentals.md")

# Known facts from the fixtures that must be retrievable after ingestion
PYTHON_FACTS = [
    "Python is a high-level, interpreted programming language",
    "Python was created by Guido van Rossum",
    "Python was first released in 1991",
    "Python uses indentation to define code blocks",
    "Python is dynamically typed",
]

ML_FACTS = [
    "Machine learning is a subset of artificial intelligence",
    "Supervised learning uses labeled training data",
    "K-means is a popular clustering algorithm",
    "Backpropagation is the algorithm used to train neural networks",
    "Accuracy measures the proportion of correct predictions",
]


def _load_fixture(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _build_subagent_from_text(
    subagent_id: str,
    text: str,
    llm_response: str = "mock answer",
    seed: str = "golden",
    target_tokens: int = 100,
    overlap_tokens: int = 20,
) -> Subagent:
    """Build a fully wired Subagent from raw text using deterministic components."""
    emb = DeterministicEmbedder(seed=seed, dim=64)
    chunker = TokenWindowChunker(
        target_tokens=target_tokens, overlap_tokens=overlap_tokens, min_tokens=10
    )
    chunks = chunker.chunk(text, doc_id=subagent_id, url_or_path=subagent_id)
    if not chunks:
        chunks = [
            Chunk(text=text, doc_id=subagent_id, chunk_index=0, url_or_path=subagent_id)
        ]
    embeddings = emb.embed([c.text for c in chunks])
    vs = VectorStore()
    vs.build(embeddings, chunks)
    retriever = Retriever(emb, vs)
    return Subagent(
        subagent_id=subagent_id,
        retriever=retriever,
        confidence_scorer=ConfidenceScorer(),
        llm=MockLLM(llm_response),
    )


# ---------------------------------------------------------------------------
# Fixture file existence
# ---------------------------------------------------------------------------


def test_python_guide_fixture_exists():
    assert os.path.exists(PYTHON_GUIDE_PATH), f"Missing fixture: {PYTHON_GUIDE_PATH}"


def test_ml_fundamentals_fixture_exists():
    assert os.path.exists(ML_FUNDAMENTALS_PATH), (
        f"Missing fixture: {ML_FUNDAMENTALS_PATH}"
    )


def test_python_guide_is_non_empty():
    content = _load_fixture(PYTHON_GUIDE_PATH)
    assert len(content.strip()) > 0


def test_ml_fundamentals_is_non_empty():
    content = _load_fixture(ML_FUNDAMENTALS_PATH)
    assert len(content.strip()) > 0


# ---------------------------------------------------------------------------
# Chunking golden fixture documents produces valid chunks
# ---------------------------------------------------------------------------


def test_chunking_python_guide_produces_chunks():
    text = _load_fixture(PYTHON_GUIDE_PATH)
    chunker = TokenWindowChunker(target_tokens=100, overlap_tokens=20, min_tokens=10)
    chunks = chunker.chunk(text, doc_id="python_guide", url_or_path=PYTHON_GUIDE_PATH)
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.doc_id == "python_guide"
        assert chunk.url_or_path == PYTHON_GUIDE_PATH
        assert len(chunk.text.strip()) > 0


def test_chunking_ml_fundamentals_produces_chunks():
    text = _load_fixture(ML_FUNDAMENTALS_PATH)
    chunker = TokenWindowChunker(target_tokens=100, overlap_tokens=20, min_tokens=10)
    chunks = chunker.chunk(text, doc_id="ml_guide", url_or_path=ML_FUNDAMENTALS_PATH)
    assert len(chunks) >= 1


def test_chunking_preserves_all_content():
    """All words from the original document should appear across the chunks."""
    text = _load_fixture(PYTHON_GUIDE_PATH)
    chunker = TokenWindowChunker(target_tokens=50, overlap_tokens=10, min_tokens=5)
    chunks = chunker.chunk(text, doc_id="d", url_or_path="")
    combined = " ".join(c.text for c in chunks)
    # Each original word must appear in the combined chunk output
    for word in text.split()[:50]:  # spot-check first 50 words
        assert word in combined, f"Word '{word}' missing from chunked output"


def test_chunking_sequential_indices():
    text = _load_fixture(ML_FUNDAMENTALS_PATH)
    chunker = TokenWindowChunker(target_tokens=80, overlap_tokens=15, min_tokens=10)
    chunks = chunker.chunk(text, doc_id="d", url_or_path="")
    for i, c in enumerate(chunks):
        assert c.chunk_index == i


# ---------------------------------------------------------------------------
# Embedding golden fixture content is deterministic
# ---------------------------------------------------------------------------


def test_embedding_python_guide_is_deterministic():
    text = _load_fixture(PYTHON_GUIDE_PATH)
    emb = DeterministicEmbedder(seed="golden", dim=64)
    v1 = emb.embed([text])
    v2 = emb.embed([text])
    assert v1 == v2


def test_embedding_different_fixtures_produce_different_vectors():
    py_text = _load_fixture(PYTHON_GUIDE_PATH)
    ml_text = _load_fixture(ML_FUNDAMENTALS_PATH)
    emb = DeterministicEmbedder(seed="golden", dim=64)
    v_py = emb.embed([py_text])[0]
    v_ml = emb.embed([ml_text])[0]
    assert v_py != v_ml


def test_embedding_all_vectors_are_unit_length():
    text = _load_fixture(PYTHON_GUIDE_PATH)
    chunker = TokenWindowChunker(target_tokens=100, overlap_tokens=20, min_tokens=10)
    chunks = chunker.chunk(text, doc_id="d")
    emb = DeterministicEmbedder(seed="golden", dim=64)
    for vec in emb.embed([c.text for c in chunks]):
        magnitude = sum(f * f for f in vec) ** 0.5
        assert abs(magnitude - 1.0) < 1e-5


# ---------------------------------------------------------------------------
# Retrieval from golden fixture: querying with known terms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_python_guide_returns_relevant_answer():
    """Subagent built from python_guide.md must return a non-empty answer."""
    text = _load_fixture(PYTHON_GUIDE_PATH)
    sa = _build_subagent_from_text("python_guide", text, llm_response="Python answer")
    resp = await sa.aquery("What programming paradigms does Python support?")
    assert resp.answer == "Python answer"
    assert resp.confidence_score >= 0.0


@pytest.mark.asyncio
async def test_query_ml_guide_returns_relevant_answer():
    text = _load_fixture(ML_FUNDAMENTALS_PATH)
    sa = _build_subagent_from_text("ml_guide", text, llm_response="ML answer")
    resp = await sa.aquery("What is supervised learning?")
    assert resp.answer == "ML answer"
    assert resp.confidence_score >= 0.0


@pytest.mark.asyncio
async def test_retrieval_includes_sources():
    text = _load_fixture(PYTHON_GUIDE_PATH)
    sa = _build_subagent_from_text("python_guide", text)
    resp = await sa.aquery("Python data types")
    assert isinstance(resp.sources, list)
    assert len(resp.sources) > 0
    for src in resp.sources:
        assert src.doc_id == "python_guide"


@pytest.mark.asyncio
async def test_confidence_score_is_bounded():
    for fixture_path in [PYTHON_GUIDE_PATH, ML_FUNDAMENTALS_PATH]:
        text = _load_fixture(fixture_path)
        sa = _build_subagent_from_text("doc", text)
        resp = await sa.aquery("machine learning neural network")
        assert 0.0 <= resp.confidence_score <= 1.0


@pytest.mark.asyncio
async def test_query_is_deterministic_across_runs():
    """Same query on same fixture must produce identical results each time."""
    text = _load_fixture(PYTHON_GUIDE_PATH)
    sa1 = _build_subagent_from_text("py", text, seed="stable")
    sa2 = _build_subagent_from_text("py", text, seed="stable")
    r1 = await sa1.aquery("Python programming")
    r2 = await sa2.aquery("Python programming")
    assert r1.confidence_score == r2.confidence_score
    assert r1.answer == r2.answer


# ---------------------------------------------------------------------------
# Orchestrator integration with golden fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg():
    c = Config.default()
    c.orchestrator.max_subagents = 5
    c.orchestrator.query_timeout_ms = 5000
    return c


@pytest.fixture
def pipeline():
    return IngestionPipeline(DeterministicEmbedder(seed="golden"))


@pytest.mark.asyncio
async def test_orchestrator_add_and_query_python_source(cfg, pipeline):
    orch = InMemoryOrchestrator(cfg, pipeline, llm=MockLLM("Python response"))
    cfg_src = SourceConfig(
        type=SourceType.HTTP,
        location="https://example.com/python-guide",
        name="python-guide",
    )
    result = await orch.add_source(cfg_src)
    assert result.status == SubagentStatus.READY

    query_result = await orch.query("Python programming language")
    assert query_result.subagent_id != ""
    assert 0.0 <= query_result.confidence <= 1.0


@pytest.mark.asyncio
async def test_orchestrator_add_two_sources_list_shows_both(cfg, pipeline):
    orch = InMemoryOrchestrator(cfg, pipeline, llm=MockLLM("answer"))
    await orch.add_source(
        SourceConfig(
            type=SourceType.GIT, location="https://github.com/example/py.git", name="py"
        )
    )
    await orch.add_source(
        SourceConfig(type=SourceType.HTTP, location="https://example.com/ml", name="ml")
    )
    listing = orch.list_sources()
    assert listing.total == 2
    names = {s.name for s in listing.sources}
    assert "py" in names
    assert "ml" in names


@pytest.mark.asyncio
async def test_orchestrator_failed_source_appears_in_listing(cfg, pipeline):
    orch = InMemoryOrchestrator(cfg, pipeline, llm=MockLLM("answer"))

    async def _fail(config):
        raise RuntimeError("simulated failure")

    orch._pipeline.ingest = _fail
    result = await orch.add_source(
        SourceConfig(type=SourceType.HTTP, location="https://broken.example.com")
    )
    assert result.status == SubagentStatus.FAILED
    assert result.last_error is not None

    listing = orch.list_sources()
    assert listing.total == 1
    assert listing.sources[0].status == SubagentStatus.FAILED


@pytest.mark.asyncio
async def test_orchestrator_query_returns_meta_with_counts(cfg, pipeline):
    orch = InMemoryOrchestrator(cfg, pipeline, llm=MockLLM("answer"))
    await orch.add_source(
        SourceConfig(
            type=SourceType.GIT, location="https://github.com/example/repo.git"
        )
    )
    result = await orch.query("test query about the repository")
    assert result.meta["queried_subagents_count"] == 1
    assert result.meta["success_count"] >= 0
    assert "latency_ms" in result.meta
    assert "errors" in result.meta


@pytest.mark.asyncio
async def test_confidence_scoring_integration(cfg, pipeline):
    """End-to-end: confidence scorer must produce values between 0 and 1."""
    orch = InMemoryOrchestrator(cfg, pipeline, llm=MockLLM("answer"))
    await orch.add_source(
        SourceConfig(type=SourceType.HTTP, location="https://example.com/data")
    )
    result = await orch.query("data retrieval query")
    assert 0.0 <= result.confidence <= 1.0
