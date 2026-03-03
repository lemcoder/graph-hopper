# MCP Server Layer Spec — Streamable HTTP (hosting-ready)

## Purpose
Provide a Python-based MCP server (MCP SDK `FastMCP`) intended for hosting via Streamable HTTP. The server must expose three tools: `add_source`, `query`, `list_sources`, be DI-friendly, and fully testable (unit + integration).

This document updates the MCP server layer for the MVP decisions:
- Supported source types for ingestion: **only `git` and `http(s)`**.
- The orchestrator enforces a configurable `max_subagents` cap (default `20`).
- `add_source` is a blocking call and must return an MCP-level error when the cap would be exceeded.
- `list_sources` returns *all known subagents* (including `pending` / `ingesting` / `ready` / `failed`) and includes `last_error` for failed entries.

---

## Mandatory decisions
- Language: Python 3.10+
- SDK: `mcp` Python SDK (>= 1.2.0)
- Server class: `FastMCP`
- Recommended transport for hosting: `streamable-http` (production)
  - Use `stateless_http=True`, `json_response=True` for scalable deployments
- For local/dev STDIO remains allowed, but tests & hosting must target HTTP transport

---

## Tool contracts (shapes)
- `add_source({ name: str, type: str, location: str, source_id?: str, auth_secret_id?: str, build_graph?: bool, metadata?: map })` -> on success: `{ subagent_id: str, status: "ready" }` or on ingestion failure: `{ subagent_id: str?, status: "failed", last_error: str }`.  
  - If the request would increase the total number of subagents above `orchestrator.max_subagents`, the call MUST return an MCP-level error describing the cap breach (see "Error semantics" below).
  - Allowed `type` values in MVP: `"git"`, `"http"`. Requests with any other `type` MUST be rejected with a validation error (tool-level error).
  - If `source_id` is supplied and matches an existing subagent, the request is treated as an update/reingest and does NOT increase the counted total for the cap check.
- `query({ query: str })` -> `{ answer: str, confidence: float, subagent_id: str, sources: [...], meta: {...} }` (see orchestrator spec for detailed shape).
- `list_sources()` -> returns a list of all known subagents with full metadata and `status` (including `failed`), ordered by `last_updated` desc (ties broken deterministically by `created_at` asc then `subagent_id` asc).

Notes:
- All MCP schemas should be represented with structured types (TypedDict / Pydantic) so `FastMCP` generates accurate schemas.

---

## DI and lifecycle
- Use FastMCP `lifespan` to initialize shared services (orchestrator, DB, caches).
- Do NOT instantiate core orchestration/persistence inside tool functions; accept via constructor, lifespan context, or dependency injection.
- Export a wiring module (e.g., `src.server.wiring`) that composes production instances and reads configuration (including `orchestrator.max_subagents`).
- Allow tests to inject fakes/mocks (OrchestratorInterface, EmbeddingInterface, InMemoryIndex).

---

## Implementation guidelines
- Implement tools as thin adapters delegating to `OrchestratorInterface`:
  - `add_source` adapter: validate args; enforce type constraints (`git`/`http` only); consult orchestrator registry for cap checks; call orchestrator to perform ingestion; convert orchestrator results to MCP tool response or raise an MCP error for cap rejection.
  - `query` adapter: pass queries to orchestrator and relay outputs. Adapter should validate input and convert exceptions to MCP-level errors where appropriate.
  - `list_sources` adapter: return the orchestrator's registry snapshot (all statuses), with stable ordering.
- Prefer structured outputs (TypedDict / Pydantic) so FastMCP generates schemas.
- Use `ctx` for logging/progress (ctx.info / ctx.report_progress).
- For Streamable HTTP hosting, logging to stdout is acceptable; still favor `logging` module.

---

## Validation & allowed inputs (MVP)
- Supported `type` values (MVP): `"git"`, `"http"` / `"https"`.
- `add_source` must validate `location` appropriate to `type`:
  - `git` — acceptable git URLs or SSH clone paths.
  - `http` / `https` — valid HTTP(s) URLs.
- Any unsupported `type` must be rejected with a validation error describing allowed types.

---

## Error semantics — cap enforcement and other failures
- Cap enforcement:
  - The orchestrator configuration key `orchestrator.max_subagents` is authoritative (default `20`).
  - `add_source` must query the orchestrator registry count (all statuses). If the request would increase total subagents above `max_subagents`, the MCP endpoint must return an MCP-level error indicating the cap was exceeded.
  - The error must be machine-readable and include:
    - `code`: e.g. `"MAX_SUBAGENTS_EXCEEDED"` (well-known string)
    - `message`: human readable (e.g. "cannot add source: maximum number of subagents (20) reached")
    - `current_count`: integer
    - `max_subagents`: integer
  - Suggested mapping to HTTP semantics for streamable-http deployments: return a non-2xx response; commonly used mapping is HTTP 409 (Conflict) for resource-limit rejections or 429 (Too Many Requests). The server adapter/wiring MUST translate into the MCP error model used by your environment so clients receive an MCP-level error and can distinguish it from a normal `add_source` response.
- Ingestion errors:
  - `add_source` performs the full ingestion pipeline synchronously and returns success `{ subagent_id, status: "ready" }` or failure `{ subagent_id?: str, status: "failed", last_error: str }`.
  - On fatal ingestion failures, partial artifacts must be preserved under `storage.failed_path`.
- Validation errors (unsupported type, missing required fields) should return a tool-level validation error (400-level logical error), not the cap-specific MCP-level error.

---

## Testing requirements
- Unit tests (pytest + pytest-asyncio)
  - Validate `add_source` adapter calls orchestrator with correct args and enforces `git`/`http(s)` only.
  - Validate cap enforcement: when orchestrator count >= `max_subagents`, `add_source` returns an MCP-level error (assert structured error body).
  - Validate reingest/update behavior: when `source_id` matches an existing subagent, `add_source` performs an update and is allowed even when at cap.
  - Validate `list_sources` adapter returns all known subagents with `status` and `last_error` for failed ones.
  - Validate error handling for invalid inputs.
- Integration tests (separate CI job)
  - Start the FastMCP `streamable_http_app()` mounted in a Starlette test app (use TestClient or run uvicorn in subprocess).
  - Use `mcp.client.streamable_http.streamable_http_client` to connect and exercise:
    - add_source: ensure it blocks/returns only after orchestrator signals ingestion complete or returns cap error when limit reached.
    - add_source reingest: attempt reingest when cap reached with `source_id` referencing existing subagent — should succeed.
    - query: two fake subagents -> aggregator picks highest-confidence.
    - list_sources: registry contains all statuses; failed entries contain `last_error`.
  - Ensure tests run deterministically (use seeded fakes for embeddings/confidences).
- Integration test timeouts and isolation:
  - Run integration suite in CI with explicit timeouts.
  - Use ephemeral ports and teardown server after tests.

---

## CI / runner recommendations
- Run unit tests on every push.
- Run integration suite on scheduled or merge jobs (longer timeout).
- Use environment variables to switch to in-memory fakes in CI.

---

## Files & layout (recommended)
- `src/server/mcp_server.py`      — FastMCP tool adapters + wiring helpers (implement cap checks in adapters or delegate to orchestrator API)
- `src/server/wiring.py`         — production wiring factory (lifespan). Read `orchestrator.max_subagents` from config and construct orchestrator instance.
- `src/orchestrator/interface.py` — protocol for orchestrator (export registry query, add_source semantics, query routing).
- `src/orchestrator/in_memory.py` — lightweight orchestrator for tests (deterministic embeddings & seeded RNG).
- `tests/unit/test_mcp_tools.py`
- `tests/integration/test_streamable_http_e2e.py`

---

## Acceptance criteria
- FastMCP server mountable via `streamable_http_app()` and runnable with `mcp.run(transport="streamable-http")` or mountable under ASGI.
- All three tools exposed with correct schemas and covered by unit tests.
- Integration tests demonstrate end-to-end `add_source`/`query`/`list_sources` using Streamable HTTP client and demonstrate cap enforcement:
  - Create `N` subagents until configured cap reached, assert further `add_source` calls return the MCP-level `MAX_SUBAGENTS_EXCEEDED` error.
  - Reingest with same `source_id` when cap reached — should succeed.
- DI allows swapping orchestrator/index/embedding implementations for tests and production.

---

## Example behaviors (concise)
- Add a new `git` source:
  - `add_source(...)` validates `type == "git"`, checks cap, then performs blocking ingestion. On success returns `{ subagent_id, status: "ready" }`. On failure returns `{ status: "failed", last_error }`.
- Add when cap reached:
  - If `source_id` omitted or new -> return MCP-level error `{ code: "MAX_SUBAGENTS_EXCEEDED", message, current_count, max_subagents }` (non-2xx).
  - If `source_id` references existing subagent -> treated as update; allowed even at cap.
- List sources:
  - `list_sources()` returns the full registry including entries with `status` values: `pending`, `ingesting`, `ready`, `failed`.
  - Each entry in the list contains `subagent_id`, `name`, `type`, `status`, `created_at`, `last_updated`, `last_error?`, `metadata?`.

---

## Operational notes
- Ensure secrets (git tokens) are resolved from the configured `secrets` store and never logged.
- Keep `add_source` blocking semantics for MVP. Revisit async ingestion and progress APIs in later iterations.
- The `max_subagents` cap simplifies resource planning and must be enforced consistently by both the MCP server layer and the orchestrator implementation.

---

If you want, I can:
- produce a FastMCP `src/server/mcp_server.py` skeleton implementing these rules, including the MCP-level error shape for cap enforcement, or
- produce deterministic unit test stubs that assert the cap semantics and `git`/`http` validation.