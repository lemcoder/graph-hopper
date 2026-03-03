# Subagent Orchestrator Spec

## Purpose
Manage subagent lifecycle and query routing for the graph-hopper runtime. The orchestrator is responsible for creating subagents from single sources, routing queries to active subagents, aggregating answers with confidences, and returning the best answer to the client via the MCP interface.

This version of the orchestrator spec codifies MVP decisions:
- Only `git` and `http(s)` source types are supported.
- `add_source` is a blocking call (full ingestion completes or fails before return).
- The orchestrator enforces a configurable `max_subagents` cap (default: 20). Attempts to add beyond the cap are rejected with an MCP-level error.
- `list_sources` returns all known subagents (including `pending`/`ingesting`/`ready`/`failed`) and includes `last_error` when present.
- Query-time selection and tie-breaking are performed during `query` processing; `list_sources` is a simple registry snapshot.

## Requirements (MVP)
- Expose exactly three MCP tools:
  - `add_source`
  - `query`
  - `list_sources`
- `add_source` blocks until ingestion and initialization of the subagent is complete (or fails, or is rejected due to cap).
- `query` routes the query to all active `ready` subagents in parallel and returns a single selected answer according to the orchestrator's scoring and tie rules.
- `list_sources` returns all known subagents and their metadata (including failed ones).
- Deterministic behavior required for tests: seeded embedding stub for tests, deterministic tie-breaking logic for query selection.
- The orchestrator must support configuration for: `max_subagents` (default 20), `query_timeout_ms` (default 500ms), and logging path/rotation.

## Config (recommended keys)
Example (YAML-like):

```
orchestrator:
  max_subagents: 20                  # default enforced cap for MVP
  max_concurrent_ingestions: 2
  default_ingestion_timeout_seconds: 60
  default_embedding_model: "default-embedding-model"
  embedding_batch_size: 64
  query_timeout_ms: 500
  log:
    path: "/var/log/graph-hopper/orchestrator.log"
    max_bytes: 104857600             # 100 MB
    backup_count: 5
  storage:
    base_path: "/var/lib/graph-hopper/subagents"
    failed_path: "/var/lib/graph-hopper/subagents/failed"
  secrets:
    store_type: "file"
    path: "/etc/graph-hopper/secrets.yaml"
```

Important:
- `max_subagents` is authoritative at runtime and must be enforced by the orchestrator (and by any MCP adapter/wiring that delegates to it).
- `default_ingestion_timeout_seconds` defines how long `add_source` will wait for ingestion before failing (default 60s).

## Supported source types (MVP)
- Only:
  - `git` (repository clones; supports `auth_secret_id` referencing operator-managed secrets)
  - `http` / `https` (websites)
- `add_source` must validate `type` and reject unsupported types with a validation error.

## Behavioral Details

### 1) Registry and state model
- A subagent lifecycle states:
  - `pending` — created and queued
  - `ingesting` / `initializing` — ingestion in progress
  - `ready` — ingestion succeeded and subagent is queryable
  - `failed` — ingestion failed; `last_error` populated
- The orchestrator maintains a registry of all known subagents. `list_sources` returns a snapshot of this registry.

### 2) add_source (ingestion semantics & cap enforcement)
- Signature (MVP):
  - Input: `source_config` with fields:
    - `type`: `"git"` | `"http"`
    - `location`: string
    - `name`: string (optional friendly name)
    - `source_id`: optional client-supplied id for idempotency / updates
    - `auth_secret_id`: optional (git-only)
    - `build_graph`: optional boolean
    - `metadata`: optional map
- Behavior:
  1. Validate inputs (type must be `git` or `http`).
  2. Cap check:
     - Determine `current_count` = number of registered subagents (all statuses).
     - If `source_id` is provided and matches an existing subagent, treat this as an update/reingest: allow the request to proceed even if `current_count >= max_subagents`.
     - Otherwise, if adding this new subagent would make `current_count + 1 > max_subagents`, reject the request immediately with an MCP-level error (see "MCP error schema" below).
  3. If allowed, proceed with ingestion in a blocking manner:
     - Resolve credentials for `git` if `auth_secret_id` provided (do NOT log secret plaintext).
     - Fetch content (shallow clone for `git` when appropriate, HTTP scrapes for website).
     - Extract documents (PDF text extraction attempted; images skipped).
     - Language detection per document (store language metadata).
     - Chunking (token-window defaults: target 500 tokens, overlap 50, min 64).
     - Embeddings (batching per configured `embedding_batch_size`).
     - Build index and optional knowledge graph.
     - Finalize: persist artifacts, mark `ready`.
  4. On ingestion success: return `{ subagent_id, status: "ready" }`.
  5. On ingestion failure: persist partial artifacts under `storage.failed_path`, mark registry entry `failed` with `last_error`, and return `{ subagent_id?: string, status: "failed", last_error: string }`.
- Ingestion timeout:
  - The orchestrator enforces `default_ingestion_timeout_seconds`. If ingestion exceeds this, mark `failed` and return `failed` with `last_error` indicating timeout.

MCP-level cap rejection:
- If cap enforcement rejects the request, the MCP endpoint MUST return a structured MCP-level error (non-2xx) containing:
  - `code`: `"MAX_SUBAGENTS_EXCEEDED"`
  - `message`: human-readable text, e.g. "cannot add source: maximum number of subagents (20) reached"
  - `current_count`: integer
  - `max_subagents`: integer
- This error enables calling coding agents to detect that the system cannot accept more subagents at this time.

### 3) Query routing & timeout policy
- `query(query_string)`:
  - Convert query to embedding (using configured model).
  - Send the query concurrently to all `ready` subagents' retrievers.
  - Enforce an overall configurable per-query timeout (`query_timeout_ms`, default 500ms). Any subagent not responding within the timeout is ignored for that query.
  - Collect (answer, confidence, provenance) from each responding subagent.
  - Failures from individual subagents during the query are treated as transient for that query only; they do not mark the subagent `failed`.
  - Select final answer using orchestrator selection rules (see below).
  - Return chosen answer plus provenance and meta (latency, counts, per-subagent errors).

### 4) Confidence scoring and normalization
- Subagents must return normalized confidence values in [0,1].
- Canonical confidence formula (documented for implementors):
  - confidence = sigmoid(a * cosine_similarity + b * keyword_score + c)
  - `cosine_similarity`: between query embedding and retrieved chunk embeddings (normalized)
  - `keyword_score`: normalized [0,1] representing keyword overlap in assembled context
  - `sigmoid` maps linear combination to (0,1)
- The orchestrator uses these confidences to compare and select the best answer.

### 5) Answer selection & tie behavior (applied at query-time)
- The orchestrator returns a single final answer (highest-confidence).
- Tie-breaking (if exact equality occurs) is deterministic and applied during query selection:
  - Sort candidate answers by: (confidence desc, created_at asc, subagent_id asc)
  - Primary answer is the first item after sorting.
  - If multiple answers share exact same confidence, include them under an `alternatives` array in the response.
- Note: tie-breaking is performed at query-time only. `list_sources` is a registry snapshot and does not apply query tie-break rules.

### 6) list_sources behavior
- `list_sources()` returns a list of all known subagents and their metadata.
- Returned metadata (MVP minimal set):
  - `subagent_id`
  - `name`
  - `type` (`GIT` | `WEBSITE` / `HTTP`)
  - `location`
  - `status` (`pending` | `ingesting` | `ready` | `failed`)
  - `created_at` (RFC3339)
  - `last_updated` (RFC3339)
  - `last_error` (optional; present when `failed`)
  - `metadata` (optional map)
- Ordering:
  - The default ordering for `list_sources` is `last_updated` descending (newest first).
  - No special tie-breaking logic for query selection is applied here; `list_sources` is intended to be a simple registry snapshot.
- There is no pagination in MVP.

### 7) Failure modes & health
- Ingestion failures:
  - `add_source` returns `status: "failed"` and `last_error` when ingestion fails.
  - Partial artifacts are preserved under `storage.failed_path` for debugging.
- Runtime health:
  - A subagent that fails during a query is treated as transiently unhealthy for that query only (not automatically demoted to `failed` unless ingestion/initialization failed repeatedly).
- Repeated initialization failures should be visible via `list_sources` (`status: failed`) and `last_error`.

### 8) Resource constraints & cap specifics
- The orchestrator enforces `max_subagents` (default 20).
- Counting rules:
  - `current_count` counts all registered subagents regardless of status.
  - Reingest/update with existing `source_id` does not increment `current_count`. An update is allowed even when `current_count >= max_subagents`.
- Additions:
  - If a new `add_source` (no existing matching `source_id`) would cause `current_count + 1 > max_subagents`, the orchestrator MUST reject the request with the MCP-level `MAX_SUBAGENTS_EXCEEDED` error.
- Rationale:
  - Hard cap enforces predictable resource usage for MVP and simplifies testing and deployments.

### 9) Testing & determinism
- The repository MUST include deterministic in-memory test doubles:
  - Deterministic embedding stub (seeded hash/SHA-derived vector generator).
  - Deterministic subagent answers for a seeded RNG.
- Required tests:
  - Cap enforcement:
    - Create `max_subagents` subagents, assert that `add_source` for another new source returns the `MAX_SUBAGENTS_EXCEEDED` MCP-level error.
    - Reingest with existing `source_id` when cap reached: assert the update is allowed and works as expected.
  - Ingestion success and failure paths:
    - `add_source` returns `ready` on success, `failed` with `last_error` on failure, and partial artifacts are saved under `failed_path`.
  - `list_sources` registry:
    - `list_sources` returns all known subagents and shows `last_error` for failed ones.
  - Query routing:
    - `query` sends to all `ready` subagents, respects `query_timeout_ms`, and uses deterministic tie-breaking in selection.
  - Supported-type validation:
    - `add_source` rejects unsupported types (non-`git`/`http`) with validation errors.

### 10) Logging & observability
- The orchestrator must log operational events to a rolling log file (rotate when file >= `log.max_bytes`) and keep log files human-readable.
- Events to log:
  - `add_source` request received (include `source_id`/`subagent_id`, `type`, `location`) — do not include secrets
  - Ingestion phase latencies (fetch, parse, embed batches, index build)
  - Number of chunks extracted
  - Errors and diagnostic info (never include secret plaintext)
  - Cap rejection events (log the `MAX_SUBAGENTS_EXCEEDED` event with `current_count` and `max_subagents`)
- Emit minimal metrics for MVP:
  - `ingestion_duration_seconds`
  - `ingestion_chunk_count`
  - `embedding_batch_count`
  - `index_build_duration_seconds`
  - `query_latency_ms`

## MCP Interface Specification (MVP)

Tool: add_source
- Description: Create and initialize a subagent from a single source. This call blocks until ingestion finishes (success or failure) or until the call is rejected due to cap enforcement.
- Arguments:
  ```
  {
    name?: string,
    type: "git" | "http",
    location: string,
    source_id?: string,
    auth_secret_id?: string,
    build_graph?: boolean,
    metadata?: map
  }
  ```
- Successful returns:
  ```
  {
    subagent_id: string,
    status: "ready"
  }
  ```
- Ingestion failure return:
  ```
  {
    subagent_id?: string,
    status: "failed",
    last_error: string
  }
  ```
- Cap rejection:
  - Returned as MCP-level non-2xx error with structured body:
    ```
    {
      code: "MAX_SUBAGENTS_EXCEEDED",
      message: "cannot add source: maximum number of subagents (20) reached",
      current_count: 20,
      max_subagents: 20
    }
    ```

Tool: query
- Description: Query all ready subagents in parallel and return the selected best answer.
- Arguments:
  ```
  { query: string }
  ```
- Returns:
  ```
  {
    answer: string,
    confidence: float,          // primary answer confidence in [0,1]
    subagent_id: string,        // subagent that produced the primary answer
    alternatives?: [            // present only if exact ties occur
      { answer: string, confidence: float, subagent_id: string }
    ],
    sources: [                  // provenance for the primary answer
      {
        subagent_id: string,
        chunk_ids: [string],
        snippet?: string,
        source_url?: string,
        confidence: float
      }
    ],
    meta: {
      latency_ms: integer,
      queried_subagents_count: integer,
      success_count: integer,
      errors: [ { subagent_id: string, error: string } ]
    }
  }
  ```

Tool: list_sources
- Description: List all known subagents and their metadata. Includes failed entries and `last_error`.
- Returns:
  ```
  {
    sources: [
      {
        subagent_id: string,
        name?: string,
        type: "GIT" | "WEBSITE",
        location: string,
        status: "pending" | "ingesting" | "ready" | "failed",
        created_at: string (RFC3339),
        last_updated: string (RFC3339),
        last_error?: string,
        metadata?: map
      },
      ...
    ],
    total: integer
  }
  ```

## Runtime Behavior Summary
- `add_source` is blocking and must finish ingestion before returning `ready` or `failed` except when the call is rejected due to cap enforcement (MCP-level error).
- `add_source` enforces `max_subagents` (default 20); reingest/update with existing `source_id` is allowed even when at cap.
- `query` sends queries in parallel to all `ready` subagents, respects `query_timeout_ms`, ignores timed-out/crashed subagents for that query, and selects the highest-confidence answer using the confidence values returned by subagents. Deterministic tie-breaking is applied at query-time only.
- `list_sources` returns the full registry (all statuses) with `last_error` for failed subagents and is a simple snapshot (ordered by `last_updated` desc). No pagination.

## Acceptance Notes
- Provide deterministic, in-memory test doubles for unit/integration tests (seeded embeddings).
- Ensure `add_source` rejects new additions when `max_subagents` would be exceeded and returns the structured `MAX_SUBAGENTS_EXCEEDED` MCP-level error.
- Ensure `add_source` allows reingest/update when `source_id` matches an existing subagent even when the cap is reached.
- Include integration tests that:
  - create `max_subagents` subagents and verify that adding another new subagent returns the cap error,
  - reingest an existing `source_id` while at cap and verify success,
  - verify `list_sources` includes failed entries with `last_error`.

## Notes / rationale
- Enforcing a hard configurable cap (`max_subagents`) keeps resource usage predictable in MVP and simplifies CI/testing.
- Restricting source types to `git` and `http(s)` reduces initial implementation complexity while leaving room to add more source types later.
- Returning failed subagents in `list_sources` provides operator visibility and simplifies debugging in early deployments.
- Blocking `add_source` simplifies client expectations for the MVP; async ingestion and progress APIs can be added in later iterations.