"""
Integration tests for the ERKS MCP server using in-memory orchestrator.
"""

import pytest
from erks.config import Config
from erks.orchestrator.in_memory import InMemoryOrchestrator
from erks.subagent.ingestion import IngestionPipeline, DeterministicEmbedder
from erks.server.mcp_server import create_mcp_server


@pytest.fixture
def small_config():
    cfg = Config.default()
    cfg.orchestrator.max_subagents = 2
    return cfg


@pytest.fixture
def orchestrator(small_config):
    pipeline = IngestionPipeline(DeterministicEmbedder(seed="integration-test"))
    return InMemoryOrchestrator(small_config, pipeline)


@pytest.fixture
def mcp_server(orchestrator):
    return create_mcp_server(orchestrator)


def get_tool(mcp, name):
    for tool in mcp._tool_manager.list_tools():
        if tool.name == name:
            return tool.fn
    raise ValueError(f"Tool {name} not found")


@pytest.mark.asyncio
async def test_add_source_then_list_sources(mcp_server):
    add_fn = get_tool(mcp_server, "add_source")
    list_fn = get_tool(mcp_server, "list_sources")

    result = await add_fn(
        type="git", location="https://github.com/example/repo.git", name="test-repo"
    )
    assert result["status"] == "ready"

    listing = list_fn()
    assert listing["total"] == 1
    assert listing["sources"][0]["name"] == "test-repo"
    assert listing["sources"][0]["status"] == "ready"


@pytest.mark.asyncio
async def test_cap_enforcement_end_to_end(mcp_server, small_config):
    add_fn = get_tool(mcp_server, "add_source")

    for i in range(small_config.orchestrator.max_subagents):
        await add_fn(type="git", location=f"https://github.com/example/repo{i}.git")

    with pytest.raises(ValueError, match="MAX_SUBAGENTS_EXCEEDED"):
        await add_fn(type="git", location="https://github.com/example/repox.git")


@pytest.mark.asyncio
async def test_reingest_at_cap(mcp_server, small_config):
    add_fn = get_tool(mcp_server, "add_source")
    list_fn = get_tool(mcp_server, "list_sources")

    source_id = "my-source"
    await add_fn(
        type="git",
        location="https://github.com/example/repo0.git",
        source_id=source_id,
    )
    for i in range(1, small_config.orchestrator.max_subagents):
        await add_fn(type="git", location=f"https://github.com/example/repo{i}.git")

    result = await add_fn(
        type="git",
        location="https://github.com/example/repo0.git",
        source_id=source_id,
    )
    assert result["status"] == "ready"

    listing = list_fn()
    assert listing["total"] == small_config.orchestrator.max_subagents


@pytest.mark.asyncio
async def test_list_sources_includes_failed_with_error(mcp_server, orchestrator):
    """Failed subagents must appear in list_sources with last_error."""

    async def failing_ingest(config):
        raise RuntimeError("simulated ingestion failure")

    orchestrator._pipeline.ingest = failing_ingest

    add_fn = get_tool(mcp_server, "add_source")
    list_fn = get_tool(mcp_server, "list_sources")

    result = await add_fn(type="http", location="https://failing-site.example.com")
    assert result["status"] == "failed"
    assert "last_error" in result

    listing = list_fn()
    assert listing["total"] == 1
    failed = listing["sources"][0]
    assert failed["status"] == "failed"
    assert failed.get("last_error") is not None


@pytest.mark.asyncio
async def test_query_end_to_end(mcp_server):
    add_fn = get_tool(mcp_server, "add_source")
    query_fn = get_tool(mcp_server, "query")

    await add_fn(type="git", location="https://github.com/example/repo1.git")

    result = await query_fn(query="What is this project about?")
    assert "answer" in result
    assert "confidence" in result
    assert "meta" in result


@pytest.mark.asyncio
async def test_invalid_source_type_rejected(mcp_server):
    add_fn = get_tool(mcp_server, "add_source")

    with pytest.raises(ValueError, match="Unsupported source type"):
        await add_fn(type="ftp", location="ftp://example.com/data")
