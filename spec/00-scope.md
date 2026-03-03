# graph-hopper — High-Level Scope (updated)

## 1. Overview

The graph-hopper is an embeddable, MCP-native runtime for creating isolated per-source knowledge units ("subagents"). Each subagent ingests a single source, builds a vector index (and optionally a knowledge graph), and answers queries grounded in its source content. The orchestrator exposes a minimal MCP toolset so coding agents can dynamically add sources, query knowledge, and enumerate known subagents.

MVP focus:
- deterministic, testable behavior
- local/in-process components (no distributed backend)
- predictable lifecycle semantics for ingestion and querying

---

## 2. Primary decisions for MVP

- Source types implemented: only `git` and `http(s)`.
- `add_source` semantics: blocking; performs full ingestion pipeline synchronously and returns final status (`ready` / `failed`) or an MCP-level error if the request is rejected (for example when the cap is exceeded).
- `list_sources` semantics: returns all known subagents and their status (including `pending` / `ingesting` / `ready` / `failed`). This is the single place to inspect system state for MVP.
- Subagent count cap: configurable `max_subagents` with a default of `20`. The orchestrator must reject `add_source` requests that would raise the total count above `max_subagents`. Reingest/update requests that supply an existing `source_id` do not increase count.
- Query routing: `query` routes to all `ready` subagents in parallel and uses the orchestrator tie-breaking logic only at query-time (not during listing).
- Determinism: tests must be deterministic — seeded embedding stub and deterministic tie-breakers for answering queries.

---

## 3. Definitions

- Subagent
  - A single-source knowledge runtime unit.
  - Maintains its own:
    - vector index (embedding store)
    - chunk store / metadata
    - optional knowledge graph
    - retriever + answer generator
  - Identified by stable `subagent_id`. Clients may provide `source_id` to request idempotent updates.

- Knowledge Source (MVP)
  - Only `git` repositories and `http(s)` websites are supported.
  - `git` ingestion may accept `auth_secret_id` referencing operator-managed secrets; secrets must not be logged.

- Status values
  - `pending` — newly created, not yet started
  - `ingesting` / `initializing` — ingestion in progress
  - `ready` — ingestion succeeded and subagent is queryable
  - `failed` — ingestion failed; `last_error` is recorded

---

## 4. System architecture (concise)

- Client (Coding Agent) → MCP Server (`FastMCP`) → Orchestrator → Subagents
- MCP tools (MVP):
  - `add_source(source_config)` → blocks until ingestion completes or fails (or is rejected due to cap)
  - `query({ query })` → returns best answer selected across subagents
  - `list_sources()` → returns all known subagents and metadata

---

## 5. Ingestion lifecycle (MVP)

- `add_source(source_config)` performs:
  1. Validation (type must be `git` or `http(s)`)
  2. Cap check: if `current_count >= max_subagents` and the request does not reference an existing `source_id`, reject the request with an MCP-level error indicating the cap has been reached.
     - If `source_id` references an existing subagent, treat as a reingest/update (allowed even when at cap).
  3. Resolve credentials (for `git` only) from secrets store (never logged).
  4. Fetch content (clone or HTTP fetch).
  5. Document extraction (including PDF text extraction attempts; images/OCR out of scope).
  6. Chunking (token-window defaults: 500 tokens target, 50 overlap, min 64).
  7. Embedding generation (single configured model; deterministic stub used in tests).
  8. Index build and optional knowledge graph.
  9. Persist artifacts to storage and mark `ready`. On failure, persist partial artifacts to `failed_path` and return `failed`.

- Ingestion timeout: default 60s (configurable).

---

## 6. Subagent persistence & failures

- On failure, partial artifacts and diagnostics are preserved under configured `storage.failed_path` for operator debugging.
- `list_sources` will include failed subagents and their `last_error` value for operator visibility.
- The orchestrator must never log secrets or plaintext credentials.

---

## 7. Cap (`max_subagents`) behavior

- Configurable orchestrator key: `orchestrator.max_subagents` (default: `20` in the default config).
- `add_source` must check the current registry size (counting all subagents across statuses).
- If `add_source` would increase total beyond `max_subagents`:
  - If `source_id` is present and matches an existing subagent → treat as update (allowed; does not increase count).
  - Otherwise → reject the request with an MCP-level error indicating `max_subagents` has been reached.
- This enforces a hard upper bound for MVP and makes resource planning deterministic.

---

## 8. Query-time behavior & tie-breaking

- `query` is sent to all `ready` subagents in parallel (respecting the configured query timeout — default 500ms).
- Each subagent returns an (answer, confidence, provenance).
- The orchestrator selects the primary answer using the configured tie-breaking rules (confidence desc, created_at asc, subagent_id asc) — applied only at query selection time, not during `list_sources`.

---

## 9. MCP responses & error semantics

- `add_source`:
  - On success: returns `{ subagent_id, status: "ready" }` (or `failed` and `last_error` when ingestion fails).
  - On cap-rejection: returns an MCP-level error (non-2xx) with a clear machine-readable message stating that the `max_subagents` limit was exceeded.
- `list_sources`: returns the full registry with `subagent_id`, `name`, `type`, `location`, `status`, `created_at`, `last_updated`, and optional `last_error`.
- `query`: returns the selected answer and provenance; includes meta about latency and per-subagent errors.

---

## 10. Config example (keys to include)

Include the following under your orchestrator config (YAML or chosen format):

- `orchestrator.max_subagents` — integer (default: 20)
- `orchestrator.max_concurrent_ingestions` — integer (default: 2)
- `orchestrator.default_ingestion_timeout_seconds` — integer (default: 60)
- `orchestrator.default_embedding_model` — string
- `orchestrator.embedding_batch_size` — integer (default: 64)
- `log.path`, `log.max_bytes`, `log.backup_count`
- `storage.base_path`, `storage.failed_path`
- `secrets.path` (file-backed store for MVP)

(Implementations must validate config on startup and enforce `max_subagents` at `add_source` time.)

---

## 11. Testing & determinism requirements

- Deterministic embedding stub for tests (seeded SHA-based vector).
- Tests should cover:
  - Cap enforcement (attempt to add `max_subagents + 1` yields MCP-level error).
  - Reingest with same `source_id` allowed even at cap.
  - `list_sources` returns all agents and includes failure info.
  - `add_source` blocking behavior and ingestion timeout behavior.
  - Only `git` and `http(s)` are accepted; other types rejected.

---

## 12. Notes & rationale

- Restricting to `git` and `http(s)` simplifies the MVP ingestion pipeline while leaving room to expand source types later.
- Returning all subagents from `list_sources` (including failed ones) provides operators full visibility through the public MCP tool in MVP and simplifies CI assertions.
- The `max_subagents` cap prevents uncontrolled resource use in early deployments and keeps behavior deterministic and testable.
- Blocking `add_source` keeps client expectations simple for the MVP; asynchronous ingestion can be added later when an explicit progress API is available.

---

If you want, I will now:
- update the other spec files to reflect these exact decisions, or
- produce a merged canonical spec document and the MCP/protobuf IDL that matches this behavior.

Tell me which next step you prefer and I’ll proceed.