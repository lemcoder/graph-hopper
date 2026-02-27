# Subagent Lifecycle & Ingestion Spec (updated)

## Purpose
Define the ingestion lifecycle for subagents: how sources are added, ingested, indexed, and made available for queries. This document specifies concrete behaviors and configuration defaults for the MVP implementation and reconciles orchestrator and MCP semantics.

Key updates in this version:
- Default `max_subagents` is 20 for the MVP.
- Supported source types for MVP: `git` and `http(s)` only.
- `add_source` enforces the configured `max_subagents` cap and returns an MCP-level error when adding a new subagent would exceed the cap.
- `list_sources` returns all known subagents (all statuses: `pending`, `ingesting`, `ready`, `failed`) and includes `last_error` for failed entries.

---

## MVP summary (decisions)
- Supported source types: `git` and `http(s)` only (no local files, no PDFs ingestion paths in MVP).
- Authentication: git authentication supported via secrets referenced by `auth_secret_id`.
- `add_source` is a blocking call that performs a full ingestion and returns a final status (`ready` / `failed`) or an MCP-level error if the call is rejected due to capacity.
- Chunking: token-window chunking (default: 500 tokens, 50 token overlap, min 64 tokens).
- No OCR for images in MVP; images and unsupported binaries are skipped.
- Single, configurable embedding model used across all subagents.
- Per-subagent vector index built in-process (in-memory/FAISS-like for MVP). Knowledge graph is optional.
- Configurable ingestion timeout (default 60s).
- On ingestion failure, partial artifacts are preserved under a `failed` area for debugging.
- No automatic retries, no webhook-triggered re-ingest, and no cross-subagent dedupe by default.
- Deterministic in-memory embedding stub used for tests (seeded hash-based vectors).

---

## Goals / Success criteria
- A subagent becomes `ready` quickly for small sources: target < 10s under nominal conditions for small sources.
- Ingestion errors are reported synchronously by `add_source` and recorded in the subagent registry (visible via `list_sources`).
- A subagent is only queryable when its status is `ready`.
- Deterministic tests: seeded deterministic embedding stub and deterministic tie-breakers for query selection.

---

## Configuration (global)
All orchestrator configuration is read from a single configuration file. Example layout (YAML-like):

```yaml
orchestrator:
  max_subagents: 20                # default hard cap for MVP (enforced)
  max_concurrent_ingestions: 2
  default_ingestion_timeout_seconds: 60
  default_embedding_model: "default-embedding-model"
  embedding_batch_size: 64
  query_timeout_ms: 500
  log:
    path: "/var/log/graph-hopper/orchestrator.log"
    max_bytes: 104857600           # 100 MB
    backup_count: 5
  storage:
    base_path: "/var/lib/graph-hopper/subagents"
    failed_path: "/var/lib/graph-hopper/subagents/failed"
  secrets:
    store_type: "file"             # MVP: simple file-backed secrets store
    path: "/etc/graph-hopper/secrets.yaml"
```

Notes:
- `max_subagents` is authoritative and enforced by `add_source`.
- Implementations should validate config at startup and fail fast on invalid values.

---

## Source types and authentication
- Supported types for MVP:
  - `git` — clones repositories. `auth_secret_id` may be supplied to reference credentials in the secrets store.
  - `http` / `https` — scrapes and extracts HTML/text from web pages (no authentication for MVP).
- `add_source` MUST validate `type` and reject unsupported types with a clear validation error.
- `source_config` structure (fields):
  - `type`: `"git"` | `"http"`
  - `location`: URL or repo path (required)
  - `source_id` (optional): client-supplied stable id for idempotency/updates. If omitted, the orchestrator generates `subagent_id`.
  - `auth_secret_id` (optional, git only): reference to secret in secrets store
  - `build_graph`: boolean (default: false)
  - `metadata`: free-form map for client metadata (optional)

Authentication:
- Git authentication uses tokens stored in the secrets store. `add_source` resolves `auth_secret_id` to credentials; secrets MUST never be logged or returned by APIs.

---

## `add_source` semantics (MCP / API)
- Synchronous, blocking call. Performs the entire ingestion pipeline and returns final status or is rejected due to capacity.
- Input: `source_config` (see above).
- Output on success:
  ```json
  { "subagent_id": "sa_...", "status": "ready" }
  ```
- Output on ingestion failure:
  ```json
  { "subagent_id": "sa_?...optional", "status": "failed", "last_error": "..." }
  ```
- Cap enforcement behavior:
  - The orchestrator checks the current registry size (`current_count`) which counts all registered subagents (all statuses).
  - If `source_config.source_id` is provided and matches an existing subagent, the call is treated as an update/reingest and does NOT increase the counted total. Updates are allowed even when `current_count >= max_subagents`.
  - If the request would create a new subagent and `(current_count + 1) > max_subagents`, the call MUST be rejected with an MCP-level error (non-2xx). The error MUST be structured and machine-readable, for example:
    ```json
    {
      "code": "MAX_SUBAGENTS_EXCEEDED",
      "message": "cannot add source: maximum number of subagents (20) reached",
      "current_count": 20,
      "max_subagents": 20
    }
    ```
  - Implementors should map this to appropriate HTTP status in streamable deployments (e.g., 409 Conflict or 429 Too Many Requests) while ensuring the MCP client receives the structured error.
- Behavior on update (`source_id` matches existing):
  - Build ingestion in a temp workspace; on success atomically swap new index into production; on failure keep old subagent as-is and return `failed`.
- Timeout:
  - `add_source` enforces `default_ingestion_timeout_seconds`. If ingestion exceeds the timeout the call fails with `status: "failed"` and `last_error` indicating a timeout.

---

## Ingestion lifecycle states
A subagent goes through these states:
- `pending` — created and enqueued for ingestion.
- `ingesting` / `initializing` — ingestion in progress.
- `ready` — ingestion completed successfully and subagent is queryable.
- `failed` — ingestion failed; `last_error` recorded; partial artifacts preserved under `failed` directory.

`list_sources` must return entries for all of these states (see `list_sources` section). Ordering should be stable and deterministic (ordered by `last_updated` desc; tie-break deterministically).

---

## Ingestion pipeline (step-by-step)
1. Validate `source_config` (type, location, optional `auth_secret_id` resolution).
2. Cap check (see "Cap enforcement" above).
3. Resolve credentials (for `git` if `auth_secret_id` present; never log secrets).
4. Fetch content:
   - `git`: clone (shallow where appropriate) into a temp workspace.
   - `http(s)`: fetch pages and normalize HTML content; follow site boundaries according to policy (configurable crawler depth in future).
5. Document extraction:
   - Extract text files and attempt PDF text extraction (text-based PDFs). Skip images (no OCR).
   - Record skipped/unsupported files in logs.
6. Language detection:
   - Detect document language; record on chunk metadata.
7. Chunking:
   - Tokenize using the tokenizer family of the embedding model.
   - Defaults:
     - target chunk size: 500 tokens
     - overlap: 50 tokens
     - min chunk size: 64 tokens
   - Preserve structural metadata per chunk: `doc_id`, `chunk_index`, `heading`, `url_or_path`, `created_at`.
8. Embeddings:
   - Use the configured embedding model for all chunks in the ingestion.
   - Batch embeddings with `embedding_batch_size` (default 64).
   - In tests use deterministic embedding stub (seeded).
9. Index build:
   - Build per-subagent vector index from computed embeddings. Index build must succeed for `ready`.
10. Optional knowledge graph:
    - If `build_graph: true`, construct knowledge graph. Graph build failures are recorded in `last_error` but do not block `ready` if index succeeded (configurable behavior).
11. Finalize:
    - On success, persist index and metadata into subagent storage and mark `ready`.
    - On failure, persist partial artifacts to `failed_path`, mark `failed`, and return `failed` with `last_error`.

---

## Per-chunk provenance metadata
Each chunk stored in the vector index should include:
- `source_id` / `subagent_id`
- `doc_id` (document-level identifier)
- `chunk_index` (0-based)
- `text_excerpt` (first N characters)
- `url` or `path` (origin)
- `heading` or section name (if available)
- `token_count`
- `language` (detected)
- `checksum` (content hash)
- `created_at`

This metadata is included in query provenance.

---

## Vector index and Knowledge Graph
- Vector index:
  - One vector index per subagent (local/in-process).
  - Built after embeddings computed; implementation may use an in-memory dense store or FAISS-like structure for MVP.
  - Index stores vectors and per-chunk provenance metadata.
- Knowledge graph:
  - Optional per-subagent component, built only when `build_graph` is requested.
  - Orchestrator does not merge graphs across subagents in MVP.

---

## Errors, retries, and failed artifacts
- No automatic retries for ingestion in MVP.
- On any fatal ingestion error, `add_source` returns `status: "failed"` and records `last_error`.
- Partial artifacts (cloned repo, computed embeddings, partial index files) are preserved under `storage.failed_path` for operator debugging.
- Operators may re-run `add_source` to attempt re-ingest after remediation.

---

## Idempotency and updates
- If `source_id` is supplied, `add_source` behaves as an update:
  - New ingestion builds into a temporary workspace.
  - On success, orchestrator atomically swaps the old subagent with new index so queries seamlessly move to updated content.
  - On failure, the old subagent remains untouched.
- If `source_id` is not supplied and the same `location` is submitted twice, the orchestrator creates distinct `subagent_id`s (clients who want dedupe must provide `source_id`).

---

## List sources (registry) — MVP behavior
- `list_sources()` returns all known subagents and their metadata (statuses included).
- Returned fields (MVP minimal set):
  - `subagent_id`
  - `name` (optional)
  - `type` (`git` | `http`)
  - `location`
  - `status` (`pending` | `ingesting` | `ready` | `failed`)
  - `created_at` (RFC3339)
  - `last_updated` (RFC3339)
  - `last_error` (optional; present for `failed`)
  - `metadata` (optional map)
- Ordering:
  - Default ordering is `last_updated` descending (newest first). Ties should be broken deterministically by `created_at` asc then `subagent_id` asc.
- No pagination in MVP. The orchestrator will enforce `max_subagents` on creation; therefore the registry size is bounded.

---

## Query-time semantics (brief)
- Orchestrator routes `query` only to subagents whose `status == ready`.
- Each subagent returns `(answer, confidence, provenance)`.
- The orchestrator enforces a per-query timeout (`query_timeout_ms`) and ignores late responders.
- The orchestrator selects the best answer using confidences returned by subagents. Tie-breaking at query-time: confidence desc, created_at asc, subagent_id asc.
- Subagent errors during query are ignored for that query and do not change `ready` status by default.

---

## Testing & determinism
- Tests must be deterministic:
  - Provide an in-memory deterministic embedding stub (`deterministic_embed(text, seed)`).
  - Deterministic tie-breaking rules for query selection.
- Required tests:
  - Cap enforcement:
    - Create `max_subagents` entries; assert a subsequent `add_source` (new `source_id`) returns the MCP-level `MAX_SUBAGENTS_EXCEEDED` error.
    - Reingest with an existing `source_id` when at cap: should be allowed and succeed/fail based on ingestion.
  - Ingestion success and failure flows, including preservation of failed artifacts.
  - `list_sources` returns all known subagents and includes `last_error` for failed ones.
  - Supported-type validation: `add_source` rejects unsupported types.

---

## Logging and observability
- Rolling plain-text logs with rotation; rotate when file ≥ `log.max_bytes` (default 100 MB).
- Do NOT log secrets or secret values.
- Log important events:
  - `add_source` received (include `source_id`/`subagent_id`, `type`, `location`, but never secrets)
  - Ingestion phases and batch latencies (fetch, chunk, embed, index build)
  - Chunk counts and embedding batch counts
  - Errors (with safe diagnostics)
  - Cap rejection events (log `MAX_SUBAGENTS_EXCEEDED` with `current_count` and `max_subagents`)
- Emit minimal metrics:
  - `ingestion_duration_seconds`
  - `ingestion_chunk_count`
  - `embedding_batch_count`
  - `index_build_duration_seconds`
  - `query_latency_ms`

---

## Storage layout (suggested)
Base path: configured `storage.base_path`.
- `storage/base_path/{subagent_id}/index/` — persisted index files & metadata
- `storage/base_path/{subagent_id}/chunks/` — chunk store (optional)
- `storage/failed/{timestamp}_{source_id}/` — failed/partial artifacts for failed ingestions

Ensure directory permissions prevent unauthorized access to artifacts and secrets.

---

## Operational notes
- Concurrency: respect `max_concurrent_ingestions` to limit resource contention.
- Resource limits: per-ingestion memory enforcement is out of scope for MVP; document expected resource usage and rely on operator-level controls (cgroups, containers).
- Secrets: secrets store must be protected; secrets are referenced by `auth_secret_id` and never included in logs or returned by APIs.
- The orchestrator must enforce `max_subagents` consistently; MCP-layer adapters should surface the structured cap error to clients.

---

## Extension points (future)
- Add `s3`, PDF, local directory ingestion, and other source types.
- Add HTTP auth support and credential flows for `http` sources.
- Add webhook-based or automatic re-ingest triggers.
- Add OCR for images.
- Add remote/pluggable vector backends.
- Add asynchronous ingestion with a progress API.
- Add automatic retries and backoff policies.

---

## Example `source_config` (semantics)
- Add a git repo (public):
  ```json
  {
    "type": "git",
    "location": "https://github.com/example/repo.git",
    "source_id": "example-repo-v1",
    "build_graph": false
  }
  ```
- Add a private git repo (auth via secret):
  ```json
  {
    "type": "git",
    "location": "git@github.com:private/repo.git",
    "auth_secret_id": "gh-private-token",
    "source_id": "private-repo-main",
    "build_graph": true
  }
  ```
- Add http site:
  ```json
  {
    "type": "http",
    "location": "https://example.com/docs/",
    "source_id": "example-docs"
  }
  ```

---

## API / MCP surface (MVP)
- `add_source(source_config) -> { subagent_id?, status, last_error? }` or MCP-level error `{ code: "MAX_SUBAGENTS_EXCEEDED", ... }` for cap breach.
- `query({ query: string }) -> { answer, confidence, subagent_id, sources, alternatives?, meta }`
- `list_sources() -> { sources: [ ... ], total }` — returns all known subagents including failed ones.

---

## Appendix: Deterministic embedding stub (testing)
- Implement a deterministic function used only by tests:
  - `vector = deterministic_embed(text, seed)` where `seed` is test-provided.
  - Example: SHA256(text + seed) transformed into N floats and normalized to unit length. This provides stable embeddings across runs for deterministic tests.

---

## Notes / rationale highlights
- Default `max_subagents = 20` enforces a bounded registry for MVP and simplifies resource planning and testing.
- Returning all subagents in `list_sources` (including `failed`) provides operator visibility and simplifies debugging in early deployments.
- Blocking `add_source` keeps client expectations simple; asynchronous ingestion can be added in later iterations with progress APIs.
- Restricting sources to `git` and `http(s)` keeps the ingestion surface area manageable for an initial robust implementation.