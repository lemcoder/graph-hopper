# MCP Server Layer Spec — Streamable HTTP (hosting-ready)

## Purpose
Provide a Python-based MCP server (MCP SDK FastMCP) intended for hosting via Streamable HTTP. The server must expose three tools: `add_source`, `query`, `list_sources`, be DI-friendly, and fully testable (unit + integration).

## Mandatory decisions
- Language: Python 3.10+
- SDK: `mcp` Python SDK (>= 1.2.0)
- Server class: `FastMCP`
- Recommended transport for hosting: `streamable-http` (production)
  - Use `stateless_http=True`, `json_response=True` for scalable deployments
  - Configure `streamable_http_path` as needed
- For local/dev STDIO remains allowed, but tests & hosting must target HTTP transport

## Tool contracts (shapes)
- add_source({ name: str, type: str, location: str }) -> { subagent_id: str, status: str }
- query({ query: str }) -> { answer: str, sources: list[str], confidence: float }
- list_sources() -> list[{ subagent_id, name, type, status, size?: int, last_updated?: str }]

## DI and lifecycle
- Use FastMCP `lifespan` to initialize shared services (orchestrator, DB, caches).
- Do NOT instantiate core orchestration/persistence inside tool functions; accept via constructor or lifespan context.
- Export a wiring module (e.g., `erks.server.wiring`) that composes production instances.
- Allow tests to inject fakes/mocks (OrchestratorInterface, EmbeddingInterface, InMemoryIndex).

## Implementation guidelines
- Implement tools as thin adapters delegating to `OrchestratorInterface`.
- Prefer structured outputs (TypedDict / Pydantic) so FastMCP generates schemas.
- Use `ctx` for logging/progress (ctx.info / ctx.report_progress).
- For Streamable HTTP hosting, logging to stdout is acceptable; still favor `logging` module.

## Testing requirements
- Unit tests (pytest + pytest-asyncio)
  - Validate tool adapters call orchestrator with correct args
  - Validate error handling and input validation
  - DI wiring tests to ensure production wiring yields compatible instances
- Integration tests (separate CI job)
  - Start the FastMCP `streamable_http_app()` mounted in a Starlette test app (use TestClient or running uvicorn in subprocess)
  - Use `mcp.client.streamable_http.streamable_http_client` to connect to `http://localhost:<port>/mcp` and exercise:
    - add_source: ensure it blocks/returns only after orchestrator signals ingestion complete
    - query: two fake subagents -> aggregator picks highest-confidence
    - list_sources: state transitions (ingesting -> ready -> error)
  - Ensure tests run deterministically (use seeded fakes for embeddings/confidences)
- Integration test timeouts and isolation:
  - Run integration suite in CI with explicit timeouts
  - Use ephemeral ports and teardown server after tests

## CI / runner recommendations
- Run unit tests on every push
- Run integration suite on scheduled or merge jobs (longer timeout)
- Use environment variables to switch to in-memory fakes in CI

## Files & layout (recommended)
- `erks/server/mcp_server.py`      — FastMCP tool adapters + wiring helpers
- `erks/server/wiring.py`         — production wiring factory (lifespan)
- `erks/orchestrator/interface.py` — protocol for orchestrator
- `erks/orchestrator/in_memory.py` — lightweight orchestrator for tests
- `tests/unit/test_mcp_tools.py`
- `tests/integration/test_streamable_http_e2e.py`

## Acceptance criteria
- FastMCP server mountable via `streamable_http_app()` and runnable with `mcp.run(transport="streamable-http")` or mounted under ASGI.
- All three tools exposed with correct schemas and covered by unit tests.
- Integration tests demonstrate end-to-end add_source/query/list_sources using Streamable HTTP client.
- DI allows swapping orchestrator/index/embedding implementations for tests and production.
