# Subagent Lifecycle & Ingestion Spec

## Purpose
Define the ingestion lifecycle for subagents: how sources are added, ingested, indexed, and made available for queries. This document specifies concrete behaviors and configuration defaults for the MVP implementation.

## MVP summary (decisions)
- Supported source types: `git` and `http(s)` only (no local files).
- Authentication: git-only authentication supported via secrets referenced in a config file.
- `add_source` is a blocking call that performs a full ingestion and returns final status (`ready` / `failed`).
- Chunking: token-window chunking (default: 500 tokens, 50 token overlap, min 64 tokens).
- Attempt PDF text extraction; images are skipped (no OCR in MVP).
- Single, configurable embedding model used across all subagents.
- Per-subagent vector index built in-process (in-memory/FAISS style for MVP). Knowledge graph is optional.
- Configurable ingestion timeout (default 60s) in the global config file.
- On ingestion failure, partial artifacts are preserved under a `/failed` area for debugging.
- No automatic retries, no webhook-triggered re-ingest, and no cross-subagent dedupe.
- Deterministic in-memory embedding stub used for tests (seeded hash-based vectors).

## Goals / Success criteria
- A subagent becomes `ready` quickly for small sources: target < 10s for small-origin sources (<=100 KB, few hundred chunks) under nominal conditions.
- Ingestion errors are reported synchronously by `add_source` and recorded in `list_sources`.
- A subagent is only queryable when its status is `ready`.
- Deterministic tests: seeded deterministic embedding stub and deterministic tie-breakers for ordering and selection.

## Config (global)
All orchestrator configuration is read from a single configuration file. Example layout (YAML-like pseudocode; exact format up to implementation):

  orchestrator:
    max_subagents: 50                # default upper bound (MVP target >= 10)
    max_concurrent_ingestions: 2
    default_ingestion_timeout_seconds: 60
    default_embedding_model: "default-embedding-model"
    embedding_batch_size: 64
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

Secrets file (MVP): the orchestrator reads credentials (git tokens) from the `secrets` store. `add_source` accepts `auth_secret_id` which references a secret stored in `secrets.yaml`. The orchestrator must never log secret plaintext.

## Source types and authentication
- Supported types for MVP:
  - `git` (clones repos; supports auth via `auth_secret_id`)
  - `http` / `https` (scrapes and extracts HTML/text; no auth in MVP)
- `source_config` structure (fields):
  - `type`: `"git"` | `"http"`
  - `location`: URL or repo path (required)
  - `source_id` (optional): client-supplied stable id for dedupe / updates. If omitted, orchestrator generates `subagent_id`.
  - `auth_secret_id` (optional, git only): reference to secret in secrets store
  - `build_graph`: boolean (default: false)
  - `metadata`: free-form map for client metadata (optional)

Authentication:
- Git authentication uses tokens stored in the secrets store. The orchestrator resolves `auth_secret_id` to credentials and uses them for the clone operation. No plaintext credentials in MCP calls.

## `add_source` semantics (MCP / API)
- Synchronous, blocking call. Performs the entire ingestion pipeline and returns final status.
- Input: `source_config` (see above)
- Output: `{ subagent_id, status: "ready" | "failed", last_error?: string }`
- Behavior:
  - If `source_config.source_id` is provided and matches an existing subagent, the call is treated as an update/reingest: the orchestrator performs ingestion to a temporary workspace and, on success, atomically swaps the old subagent for the new one.
  - If no `source_id` given, a new `subagent_id` is generated and a new subagent is created.
  - The call enforces a global ingestion timeout configurable in the config file (default 60s). If the timeout is reached the ingestion is considered failed and returns `failed`.
  - On failure, partial artifacts are preserved in the configured `failed_path` for debugging; the subagent is not marked `ready` and is not queryable.
  - No progress API or cancel operation in MVP.
  - No automatic retries; operator can call `add_source` again to reattempt after fixing issues.

## Ingestion lifecycle states
A subagent goes through these states:
- `pending` — created and enqueued for ingestion.
- `ingesting` — ingestion in progress.
- `ready` — ingestion completed successfully and subagent is queryable.
- `failed` — ingestion failed; `last_error` recorded; partial artifacts preserved under `failed` directory.

`list_sources` must show stable ordering (deterministic) and include `subagent_id`, `name` (if provided), `type`, `location`, `status`, `created_at`, and `last_error` if any.

## Ingestion pipeline (step-by-step)
1. Resolve `source_config` and credentials (if any).
2. Fetch content:
   - For `git`: clone (shallow where appropriate) into a temp workspace.
   - For `http(s)`: fetch and extract visible HTML content (title, headings, body text, and per-URL metadata).
3. Document extraction:
   - Extract text files and attempt PDF extraction (text-based PDFs). For PDFs use a PDF text extractor; images are skipped (no OCR).
   - Skipped/unsupported binaries are recorded in logs and not included in chunks.
4. Language detection:
   - Detect document language. If language is unsupported, either skip or mark chunk with language metadata. (MVP: keep chunks but include detected-language field so orchestrator/tests can filter if desired.)
5. Chunking:
   - Tokenize using the same tokenizer family as the embedding model.
   - Defaults:
     - target chunk size: 500 tokens
     - overlap: 50 tokens
     - min chunk size: 64 tokens
   - Preserve structural metadata on each chunk: `doc_id`, `chunk_index`, `heading`, `url_or_path`, `created_at`.
   - Store per-chunk provenance metadata (see below).
6. Embeddings:
   - Use the configured embedding model (single global model) for all chunks within the ingestion. Batch embeddings with `embedding_batch_size` (default 64).
   - Embedding API calls are synchronous in the `add_source` flow. In tests, use deterministic embedding stub.
7. Index build:
   - Build the per-subagent vector index from computed embeddings. Index build must succeed for the subagent to be `ready`.
8. Optional Knowledge Graph:
   - If `build_graph: true`, construct the knowledge graph after or alongside indexing. Graph build failure does not block readiness in the recommended configuration unless explicitly configured otherwise. In MVP, graph errors are recorded in `last_error` but vector index success sets `ready`.
9. Finalize:
   - On success, persist index and metadata into subagent storage, mark `ready`.
   - On failure, persist artifacts to `failed_path` and return `failed` with `last_error`.

## Per-chunk provenance metadata
Each chunk stored in the vector index should include:
- `source_id` / `subagent_id`
- `doc_id` (document-level identifier)
- `chunk_index` (0-based)
- `text_excerpt` (first N characters for quick previews)
- `url` or `path` (origin)
- `heading` or section name (if available)
- `token_count`
- `language` (detected)
- `checksum` (content hash)
- `created_at`

This metadata is returned in query provenance.

## Vector index and Knowledge Graph
- Vector index:
  - One vector index per subagent (local/in-process).
  - Built after embeddings computed. Implementation may be an in-memory dense index or FAISS-like structure.
  - Index stores vectors and per-chunk provenance metadata.
- Knowledge graph:
  - Optional per-subagent component, built only when requested via `build_graph`.
  - In MVP, the orchestrator does not merge or query across subagent graphs. Graph errors do not block index readiness by default (but are recorded).

## Errors, retries, and failed artifacts
- No automatic retries for ingestion in MVP.
- On any fatal ingestion error, `add_source` returns `failed` and records `last_error`.
- Partial artifacts (cloned repo, computed embeddings, partial index files) are preserved under `failed_path` for operator debugging.
- Operators can re-run `add_source` to attempt re-ingest after remediation.

## Idempotency and updates
- If `source_id` is supplied, `add_source` is treated as an update:
  - New ingestion builds into a temporary workspace.
  - On success, orchestrator atomically swaps the old subagent with the new index so queries seamlessly move to the new content.
  - On failure, the old subagent remains untouched.
- If `source_id` is not supplied and the same `location` is submitted twice, orchestrator will create distinct `subagent_id`s (clients who want dedupe must provide `source_id`).

## Query-time semantics (brief)
- Orchestrator routes `query` only to subagents whose status is `ready`.
- Each subagent returns an answer + confidence + provenance.
- The orchestrator enforces a global query timeout (configured elsewhere); responses after the timeout are ignored for that query. (For orchestrator config see `02-orchestrator.md`.)
- Subagent errors during query are ignored for that query and do not change `ready` status.

## Testing & determinism
- Tests must be deterministic:
  - Provide an in-memory deterministic embedding stub that computes embeddings as a hash-derived vector seeded by a test seed.
  - Deterministic tie-breaking rules for answer selection and `list_sources` ordering:
    - Primary ordering: confidence (desc), created_at (asc), subagent_id (asc) — deterministic if metadata is stable.
- Provide unit and integration tests to cover:
  - Ingestion success and failure paths.
  - Timeout behavior for ingestion.
  - Chunking and provenance metadata correctness.
  - Deterministic embeddings and tie-breakers.

## Logging and observability
- Rolling plain-text logs with rotation; rotate when file ≥ `log.max_bytes` (default 100 MB).
- Log important events at ingestion-time:
  - `add_source` received (include `source_id`/`subagent_id`, `type`, `location`).
  - Ingestion phases and latencies (fetch, parse, chunk, embed batches, index build, graph build).
  - Number of chunks extracted.
  - Embedding API call counts and batch durations.
  - Errors (with non-sensitive diagnostic details — never log secrets).
- Emit basic metrics (MVP):
  - `ingestion_duration_seconds`
  - `ingestion_chunk_count`
  - `embedding_batch_count`
  - `index_build_duration_seconds`
- Logs should include request identifiers to trace a single `add_source` request.

## Storage layout (suggested)
Base path: configured `storage.base_path`.
- `storage/base_path/{subagent_id}/index/` — persisted index files & metadata
- `storage/base_path/{subagent_id}/chunks/` — chunk store (optional)
- `storage/failed/{timestamp}_{source_id}/` — failed/partial artifacts for failed ingestions
Ensure directory permissions prevent unauthorized access to artifacts and secrets.

## Operational notes
- Concurrency: respect `max_concurrent_ingestions` to limit resource contention.
- Resource limits: per-ingestion memory enforcement is out of scope for MVP; document expected resource usage and enforce via operator-level controls (cgroups, containers).
- Secrets: secrets store must be protected; secrets are referenced by `auth_secret_id` and never included in logs or returned by APIs.

## Extension points (future)
- Add `s3` and other cloud storage sources.
- Add HTTP auth support and secret-less credential flows.
- Add webhook-based or automatic re-ingest triggers.
- Add optional OCR for images.
- Add pluggable vector backends (remote indexes).
- Add in-progress ingestion and cancel APIs.
- Add automatic retries and backoff policies.

## Example `source_config` (semantics)
- Add a git repo (public):

  - `type`: "git"
  - `location`: "https://github.com/example/repo.git"
  - `source_id`: "example-repo-v1"   # optional
  - `build_graph`: false

- Add a private git repo (auth via secret):

  - `type`: "git"
  - `location`: "git@github.com:private/repo.git"
  - `auth_secret_id`: "gh-private-token"
  - `source_id`: "private-repo-main"
  - `build_graph`: true

- Add http site:

  - `type`: "http"
  - `location`: "https://example.com/docs/"
  - `source_id`: "example-docs"

## API / MCP surface (MVP)
- `add_source(source_config) -> { subagent_id, status, last_error? }`
- `query({ query: string }) -> { answer, confidence, provenance, alternatives? }`
- `list_sources() -> [ { subagent_id, name?, type, location, status, created_at, last_error? } ]`

The orchestrator exposes only these three tools in MVP. Administrative operations such as pause/resume/remove are out of scope for the MVP public API (they may exist in internal operator tooling).

## Appendix: Deterministic embedding stub (testing)
- Implement a deterministic function used only by tests:
  - `vector = deterministic_embed(text, seed)` where `seed` is test-provided.
  - Example approach: take SHA256(text + seed) and split into N floats normalized to [-1,1] or [0,1] as required by vector similarity. This provides stable embeddings across runs for deterministic tests.

## Notes / rationale highlights
- Blocking `add_source` simplifies lifecycle and client expectations for the MVP.
- Preserving failed artifacts in a `failed` area helps operators debug without losing context.
- Keeping git authentication limited to `auth_secret_id` in a secrets store reduces risk of leaking credentials.
- Token-based chunking aligned with the embedding model keeps chunks appropriate for semantic quality.
- Deterministic test strategies ensure reproducible behavior in CI.

--- End of spec for `03-subagent-ingestion.md`
