import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.models import (
    AddSourceResult,
    CapExceededError,
    ListSourcesResult,
    QueryResult,
    SourceConfig,
    SourceType,
    SubagentRecord,
    AddSourceResult,
    QueryResult,
    ListSourcesResult,
    CapExceededError,
    SubagentStatus,
)
from src.models import (
    ValidationError as GraphHopperValidationError,
)
from src.server.mcp_server import create_mcp_server


def make_mock_orchestrator():
    orch = MagicMock()
    orch.add_source = AsyncMock()
    orch.query = AsyncMock()
    orch.list_sources = MagicMock()
    return orch


def make_subagent_record(
    subagent_id="sa_001", status=SubagentStatus.READY, last_error=None
):
    now = datetime.now(timezone.utc)
    return SubagentRecord(
        subagent_id=subagent_id,
        type=SourceType.GIT,
        location="https://github.com/example/repo.git",
        status=status,
        created_at=now,
        last_updated=now,
        last_error=last_error,
    )


@pytest.mark.asyncio
async def test_add_source_calls_orchestrator():
    orch = make_mock_orchestrator()
    orch.add_source.return_value = AddSourceResult(
        subagent_id="sa_001", status=SubagentStatus.READY
    )
    mcp = create_mcp_server(orch)

    tool_fn = None
    for tool in mcp._tool_manager.list_tools():
        if tool.name == "add_source":
            tool_fn = tool.fn
            break
    assert tool_fn is not None

    result = await tool_fn(type="git", location="https://github.com/example/repo.git")
    assert result["status"] == "ready"
    assert result["subagent_id"] == "sa_001"
    orch.add_source.assert_called_once()


@pytest.mark.asyncio
async def test_add_source_rejects_invalid_type():
    orch = make_mock_orchestrator()
    mcp = create_mcp_server(orch)

    tool_fn = None
    for tool in mcp._tool_manager.list_tools():
        if tool.name == "add_source":
            tool_fn = tool.fn
            break

    with pytest.raises(ValueError, match="Unsupported source type"):
        await tool_fn(type="ftp", location="ftp://example.com")


@pytest.mark.asyncio
async def test_add_source_cap_exceeded_raises():
    orch = make_mock_orchestrator()
    orch.add_source.side_effect = CapExceededError(current_count=3, max_subagents=3)
    mcp = create_mcp_server(orch)

    tool_fn = None
    for tool in mcp._tool_manager.list_tools():
        if tool.name == "add_source":
            tool_fn = tool.fn
            break

    with pytest.raises(ValueError, match="MAX_SUBAGENTS_EXCEEDED"):
        await tool_fn(type="git", location="https://github.com/example/repo.git")


@pytest.mark.asyncio
async def test_add_source_allows_http():
    orch = make_mock_orchestrator()
    orch.add_source.return_value = AddSourceResult(
        subagent_id="sa_002", status=SubagentStatus.READY
    )
    mcp = create_mcp_server(orch)

    tool_fn = None
    for tool in mcp._tool_manager.list_tools():
        if tool.name == "add_source":
            tool_fn = tool.fn
            break

    result = await tool_fn(type="http", location="https://example.com/docs")
    assert result["status"] == "ready"


@pytest.mark.asyncio
async def test_add_source_allows_https_normalized():
    orch = make_mock_orchestrator()
    orch.add_source.return_value = AddSourceResult(
        subagent_id="sa_003", status=SubagentStatus.READY
    )
    mcp = create_mcp_server(orch)

    tool_fn = None
    for tool in mcp._tool_manager.list_tools():
        if tool.name == "add_source":
            tool_fn = tool.fn
            break

    result = await tool_fn(type="https", location="https://example.com/docs")
    assert result["status"] == "ready"


@pytest.mark.asyncio
async def test_query_calls_orchestrator():
    orch = make_mock_orchestrator()
    orch.query.return_value = QueryResult(
        answer="Test answer",
        confidence=0.9,
        subagent_id="sa_001",
        meta={
            "latency_ms": 5,
            "queried_subagents_count": 1,
            "success_count": 1,
            "errors": [],
        },
    )
    mcp = create_mcp_server(orch)

    tool_fn = None
    for tool in mcp._tool_manager.list_tools():
        if tool.name == "query":
            tool_fn = tool.fn
            break

    result = await tool_fn(query="What is this?")
    assert result["answer"] == "Test answer"
    assert result["confidence"] == 0.9
    orch.query.assert_called_once_with("What is this?")


@pytest.mark.asyncio
async def test_query_rejects_empty_query():
    orch = make_mock_orchestrator()
    mcp = create_mcp_server(orch)

    tool_fn = None
    for tool in mcp._tool_manager.list_tools():
        if tool.name == "query":
            tool_fn = tool.fn
            break

    with pytest.raises(ValueError):
        await tool_fn(query="")


def test_list_sources_returns_all():
    orch = make_mock_orchestrator()
    records = [
        make_subagent_record("sa_001", SubagentStatus.READY),
        make_subagent_record(
            "sa_002", SubagentStatus.FAILED, last_error="connection failed"
        ),
    ]
    orch.list_sources.return_value = ListSourcesResult(
        sources=records, total=2, max_allowed=20
    )
    mcp = create_mcp_server(orch)

    tool_fn = None
    for tool in mcp._tool_manager.list_tools():
        if tool.name == "list_sources":
            tool_fn = tool.fn
            break

    result = tool_fn()
    assert result["total"] == 2
    assert result["max_allowed"] == 20
    statuses = {s["subagent_id"]: s["status"] for s in result["sources"]}
    assert statuses["sa_001"] == "ready"
    assert statuses["sa_002"] == "failed"

    failed = next(s for s in result["sources"] if s["subagent_id"] == "sa_002")
    assert failed.get("last_error") == "connection failed"
