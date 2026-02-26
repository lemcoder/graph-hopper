# Subagent Orchestrator Spec

## Purpose
Manage subagent lifecycle and query routing for the ERKS runtime. The orchestrator is responsible for creating subagents from single sources, routing queries to active subagents, aggregating answers with confidences, and returning the best answer to the client via the MCP interface.

## Requirements (MVP)
- Provide and expose exactly three MCP tools for MVP:
  - `add_source`
  - `query`
  - `list_sources`
- `add_source` blocks until ingestion and initialization of the subagent is complete (MVP behavior). No background ingestion, no progress API, and no cancel API in MVP.
- `query` routes the query to all active/ready subagents in parallel and returns a single selected answer (see selection rules below). `query` accepts no optional source-selection parameters in MVP.
- `list_sources` returns all known subagents and includes metadata (see Response Format).
- The orchestrator must aggregate answers and confidences produced by subagents and select a final answer according to the configured scoring and tie rules.
- No additional lifecycle APIs (pause, resume, remove, reload, update) are provided in MVP. To clear the system scope the user restarts the service.

## Success Criteria
- Orchestrator can manage a configurable maximum number of subagents (MVP target: ≥10).
- Per-query orchestration should be capable of returning the best answer within the configured timeout (default target: 500ms).
- The orchestrator tolerates subagent crashes during queries by ignoring crashed/failed responses and returning the best available answer from healthy subagents.
- Deterministic behavior for tests: tie-breaking and `list_sources` ordering must be stable and deterministic.

## Behavioral Details

### 1) add_source (ingestion semantics)
- `add_source(source_config) → { subagent_id, status }`
- In MVP `add_source` blocks: it performs the full ingestion pipeline (fetch, parse, chunk, embed, index, knowledge-graph build) and does not return until the subagent is fully initialized or ingestion has definitively failed.
- Return `status` values: `"ready"` on success, or `"failed"` on unrecoverable ingestion errors. No partial/async readiness states are exposed for MVP.
- There is no cancellation or progress API in MVP.

### 2) Query routing & timeout policy
- `query(query_string)` routes the query to all active `ready` subagents in parallel.
- The orchestrator enforces an overall configurable query timeout (default 500ms). Any subagent that fails to respond within that timeout is ignored for that query.
- If a subagent crashes or raises an error during a query, the orchestrator ignores that subagent's response for that query and continues with others. Crashes during a query do not mark the subagent as permanently unhealthy for subsequent queries (unless it repeatedly fails during initialization).
- There are no concurrency limits in MVP: the orchestrator will attempt to query all ready subagents in parallel (respecting system resource constraints is an implementation concern).

### 3) Confidence scoring and normalization
- In MVP all subagents use the same embedding model; the orchestrator can therefore directly compare subagent confidences without additional cross-model calibration.
- Confidence outputs must be normalized to [0,1].
- The canonical confidence formula used by subagents (and documented for implementers) is:
  - confidence = sigmoid(a * cosine_similarity + b * keyword_score + c)
  - where `cosine_similarity` is the cosine similarity between query embedding and retrieved chunk embeddings (normalized as appropriate), `keyword_score` is a normalized metric in [0,1] representing query keyword overlap in retrieved context, and `sigmoid` maps the linear combination to (0,1).
- The orchestrator expects subagents to return their computed confidence in [0,1]; the orchestrator selects based on these values.

### 4) Answer selection & tie behavior
- The orchestrator returns a single final answer (the highest-confidence answer).
- In the rare event of an exact tie on confidence, the orchestrator includes all tied answers in the `alternatives` field of the response in addition to selecting a primary best-answer. Ordering and tie-breaking are deterministic: sort by (confidence desc, created_at asc, subagent_id asc) to determine the primary answer and list tied alternatives deterministically.
- The returned response must indicate which subagent produced the chosen answer (see Response Format).

### 5) Failure modes & health
- If ingestion fails (e.g., cannot read data or create index/graph), `add_source` returns `status: "failed"` and the `list_sources` metadata includes `last_error`.
- If a subagent fails during a query, treat that failure as transient for that query only; it does not cause the subagent to be permanently marked failed for future queries by default.
- Repeated initialization failures should be surfaced via `list_sources` metadata.

### 6) Knowledge graph scope
- Knowledge graph construction and usage is internal to the subagent. The orchestrator does not access or combine subagent graphs and does not perform graph-based reranking for MVP.

### 7) Resource constraints
- The orchestrator enforces a configurable maximum number of subagents (configurable via runtime config). The default target for MVP is to support ≥10 concurrently active subagents.
- Per-subagent memory accounting and enforcement is out of scope for MVP (implementations may document expected memory usage per-subagent).

### 8) Testing & determinism
- Test doubles (deterministic in-memory subagents / orchestrator) are required in the repo for unit and integration tests.
- Tests must be deterministic: subagents used in tests must produce deterministic embeddings and confidence values for a given seeded RNG.
- The orchestrator must break ties deterministically and `list_sources` must return stable ordering for reproducible tests.

### 9) Logging & observability
- The orchestrator must log operational events to a file using rolling logs so that any single log file remains < 100MB.
- Logs should be human-readable lines (not overly verbose structured JSON), similar to common system logging (e.g., succinct logcat-style lines). Log entries should include timestamps and the event type (ingestion start/finish/fail, query start/finish, subagent error).
- Implementations may add structured metrics and internal traces, but for MVP the logging requirement above is sufficient.

## MCP Interface Specification (MVP)

Tool: add_source
- Description: Create and initialize a subagent from a single source. This call blocks until ingestion finishes (success or failure).
- Arguments:
  ```
  {
    name: string
    type: string
    location: string
  }
  ```
- Returns:
  ```
  {
    subagent_id: string
    status: "ready" | "failed"
    last_error?: string
  }
  ```

Tool: query
- Description: Query all ready subagents in parallel and return the selected best answer.
- Arguments:
  ```
  {
    query: string
  }
  ```
- Returns:
  ```
  {
    answer: string,
    confidence: float,          // primary answer confidence in [0,1]
    subagent_id: string,        // subagent that produced the primary answer
    alternatives?: [            // present only if there are exact ties
      {
        answer: string,
        confidence: float,
        subagent_id: string
      }
    ],
    sources: [                  // provenance for the primary answer (and alternatives can include their own)
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
- Description: List all known subagents and their metadata.
- Returns:
  ```
  [
    {
      subagent_id: string,
      name: string,
      type: string,
      location: string,
      status: "ready" | "failed" | "initializing",
      created_at: string (RFC3339),
      last_error?: string
    }
  ]
  ```

## Runtime Behavior Summary

- `add_source` is blocking and must finish ingestion before returning `ready` or `failed`.
- `query` sends queries in parallel to all ready subagents, respects an overall configurable timeout (default 500ms), ignores subagents that time out or crash for that query, and selects the highest-confidence answer using the sigmoid-based confidence formula produced by subagents.
- The orchestrator returns a single primary answer, the producing subagent, and deterministic alternatives when exact ties occur.
- No lifecycle operations beyond the three MCP tools are available in MVP; to clear or change system scope, restart the runtime.

## Implementation & Acceptance Notes
- Provide deterministic, in-memory test doubles for subagents (seeded embeddings) to be used in unit/integration tests.
- Ensure logs are written to a rolling file (<100MB per file) with concise human-readable log lines.
- The orchestrator should expose configuration for: max_subagents, query_timeout_ms, and logging path/rotation settings.
- The orchestrator must maintain deterministic ordering for `list_sources` and tie-breaking to support reproducible tests and CI assertions.
