"""FastMCP server implementing three tools: add_source, query, list_sources."""
from __future__ import annotations

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

from erks.models import (
    AddSourceResult,
    CapExceededError,
    ListSourcesResult,
    QueryResult,
    SourceConfig,
    SourceType,
    ValidationError as ErksValidationError,
)
from erks.orchestrator.interface import OrchestratorInterface

logger = logging.getLogger(__name__)


def create_mcp_server(orchestrator: OrchestratorInterface, name: str = "ERKS") -> FastMCP:
    """Factory that creates a FastMCP server wired to the given orchestrator."""
    mcp = FastMCP(name)

    @mcp.tool()
    async def add_source(
        type: str,
        location: str,
        name: Optional[str] = None,
        source_id: Optional[str] = None,
        auth_secret_id: Optional[str] = None,
        build_graph: bool = False,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Create and initialize a subagent from a single source. Blocks until ingestion finishes.
        Supported types: git, http.
        Returns { subagent_id, status } on success or failure, or raises an error when cap exceeded.
        """
        try:
            type_lower = type.lower()
            if type_lower == "https":
                type_lower = "http"

            try:
                source_type = SourceType(type_lower)
            except ValueError:
                raise ErksValidationError(
                    f"Unsupported source type '{type}'. Allowed: git, http"
                )

            config = SourceConfig(
                type=source_type,
                location=location,
                name=name,
                source_id=source_id,
                auth_secret_id=auth_secret_id,
                build_graph=build_graph,
                metadata=metadata,
            )
            result: AddSourceResult = await orchestrator.add_source(config)
            return result.model_dump(exclude_none=True)

        except CapExceededError as exc:
            raise ValueError(
                f"MAX_SUBAGENTS_EXCEEDED: {exc.message} "
                f"(current_count={exc.current_count}, max_subagents={exc.max_subagents})"
            )
        except ErksValidationError as exc:
            raise ValueError(str(exc))

    @mcp.tool()
    async def query(query: str) -> dict:
        """Query all ready subagents in parallel and return the best answer."""
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        result: QueryResult = await orchestrator.query(query)
        return result.model_dump(exclude_none=True)

    @mcp.tool()
    def list_sources() -> dict:
        """List all known subagents and their metadata. Includes failed entries and last_error."""
        result: ListSourcesResult = orchestrator.list_sources()
        sources = []
        for s in result.sources:
            d = s.model_dump(exclude_none=False)
            d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
            d["last_updated"] = (
                d["last_updated"].isoformat() if d.get("last_updated") else None
            )
            d["type"] = d["type"].value if hasattr(d.get("type"), "value") else d.get("type")
            d["status"] = (
                d["status"].value if hasattr(d.get("status"), "value") else d.get("status")
            )
            sources.append({k: v for k, v in d.items() if v is not None or k == "last_error"})
        return {
            "sources": sources,
            "total": result.total,
            "max_allowed": result.max_allowed,
        }

    return mcp
