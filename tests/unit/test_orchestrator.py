import pytest
import asyncio
from erks.config import Config
from erks.models import (
    SourceConfig,
    SourceType,
    SubagentStatus,
    CapExceededError,
    ValidationError as ErksValidationError,
)
from erks.orchestrator.in_memory import InMemoryOrchestrator
from erks.subagent.ingestion import IngestionPipeline, DeterministicEmbedder


@pytest.fixture
def config():
    cfg = Config.default()
    cfg.orchestrator.max_subagents = 3
    return cfg


@pytest.fixture
def orchestrator(config):
    pipeline = IngestionPipeline(DeterministicEmbedder(seed="test"))
    return InMemoryOrchestrator(config, pipeline)


def make_git_config(name="test", location="https://github.com/example/repo.git", source_id=None):
    return SourceConfig(type=SourceType.GIT, location=location, name=name, source_id=source_id)


def make_http_config(name="test", location="https://example.com/docs", source_id=None):
    return SourceConfig(type=SourceType.HTTP, location=location, name=name, source_id=source_id)


@pytest.mark.asyncio
async def test_add_source_git_success(orchestrator):
    result = await orchestrator.add_source(make_git_config())
    assert result.status == SubagentStatus.READY
    assert result.subagent_id is not None


@pytest.mark.asyncio
async def test_add_source_http_success(orchestrator):
    result = await orchestrator.add_source(make_http_config())
    assert result.status == SubagentStatus.READY


@pytest.mark.asyncio
async def test_add_source_invalid_type(orchestrator):
    with pytest.raises(Exception):
        orchestrator._validate_source_type("invalid")


@pytest.mark.asyncio
async def test_cap_enforcement(orchestrator, config):
    for i in range(config.orchestrator.max_subagents):
        result = await orchestrator.add_source(
            make_git_config(
                name=f"source_{i}",
                location=f"https://github.com/example/repo{i}.git",
            )
        )
        assert result.status == SubagentStatus.READY

    with pytest.raises(CapExceededError) as exc_info:
        await orchestrator.add_source(
            make_git_config(name="over_cap", location="https://github.com/example/repox.git")
        )

    assert exc_info.value.current_count == config.orchestrator.max_subagents
    assert exc_info.value.max_subagents == config.orchestrator.max_subagents


@pytest.mark.asyncio
async def test_reingest_at_cap(orchestrator, config):
    """Reingest with existing source_id allowed even at cap."""
    source_id = "existing-source"
    await orchestrator.add_source(make_git_config(source_id=source_id))

    for i in range(config.orchestrator.max_subagents - 1):
        await orchestrator.add_source(
            make_git_config(
                name=f"source_{i}",
                location=f"https://github.com/example/repo{i}.git",
            )
        )

    result = await orchestrator.add_source(make_git_config(source_id=source_id))
    assert result.status == SubagentStatus.READY


@pytest.mark.asyncio
async def test_list_sources_empty(orchestrator):
    result = orchestrator.list_sources()
    assert result.sources == []
    assert result.total == 0


@pytest.mark.asyncio
async def test_list_sources_includes_all_statuses(orchestrator):
    await orchestrator.add_source(
        make_git_config(name="src1", location="https://github.com/example/repo1.git")
    )
    listing = orchestrator.list_sources()
    assert listing.total == 1
    assert listing.sources[0].status == SubagentStatus.READY


@pytest.mark.asyncio
async def test_list_sources_ordering(orchestrator):
    """list_sources should be ordered by last_updated desc."""
    await orchestrator.add_source(
        make_git_config(name="first", location="https://github.com/example/r1.git")
    )
    await orchestrator.add_source(
        make_git_config(name="second", location="https://github.com/example/r2.git")
    )
    listing = orchestrator.list_sources()
    assert listing.total == 2
    assert listing.sources[0].last_updated >= listing.sources[1].last_updated


@pytest.mark.asyncio
async def test_query_no_ready_agents(orchestrator):
    result = await orchestrator.query("test query")
    assert result.confidence == 0.0
    assert "No ready subagents" in result.answer


@pytest.mark.asyncio
async def test_query_with_ready_agent(orchestrator):
    await orchestrator.add_source(make_git_config())
    result = await orchestrator.query("test query")
    assert result.confidence >= 0.0
    assert result.subagent_id != ""


@pytest.mark.asyncio
async def test_deterministic_embedder():
    from erks.subagent.ingestion import DeterministicEmbedder

    emb = DeterministicEmbedder(seed="test", dim=64)
    v1 = emb.embed(["hello world"])
    v2 = emb.embed(["hello world"])
    assert v1 == v2  # deterministic
    assert len(v1[0]) == 64
    magnitude = sum(f * f for f in v1[0]) ** 0.5
    assert abs(magnitude - 1.0) < 1e-5
