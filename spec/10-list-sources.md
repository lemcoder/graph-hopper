# Source Listing & Metadata Spec (v0.3)

Purpose
-------
This document specifies the `list_sources` MCP tool for the graph-hopper updated to match orchestrator and ingestion decisions for the MVP.

Summary of key MVP decisions reflected here
- The orchestrator supports only `git` and `http(s)` sources in MVP.
- `add_source` is a blocking call and enforces a configurable `max_subagents` cap (default 20). Adding a new subagent that would exceed the cap is disallowed and must return an MCP-level error.
- `list_sources` returns all known subagents and their metadata. This includes subagents in `pending` / `ingesting` / `ready` / `failed` states; failed entries include `last_error`.
- There is no pagination in MVP. The `max_subagents` cap bounds the registry size in practice.

Goals & Constraints
-------------------
- The MCP server exposes a `list_sources` tool that returns all known subagents (bounded by configured `max_subagents`).
- Only `git` and `http(s)` are accepted as source types by `add_source` in the MVP; `list_sources` will reflect the type stored for each subagent.
- `add_source` must enforce `orchestrator.max_subagents` (default 20). If an addition would exceed the cap, it must be rejected with a structured MCP-level error `MAX_SUBAGENTS_EXCEEDED`.
- `list_sources` is a simple registry snapshot — no filters, no pagination, and ordering is deterministic.

High-level semantics
--------------------
- Clients call `list_sources` to obtain a snapshot of all known subagents (across statuses). This is the authoritative registry view for MVP.
- `list_sources` must include failed subagents and their `last_error` so operators and clients can inspect ingestion failures via MCP.
- `add_source` remains the only ingestion API in the MVP and is blocking; because of cap enforcement, clients may be rejected when the system is at capacity.

What `list_sources` returns
---------------------------
- The response is a small structured object containing a list of `SourceMetadata` records and a `total` count.
- Each `SourceMetadata` record contains:
  - `subagent_id` (string) — stable unique id
  - `name` (string, optional)
  - `type` (enum) — MVP uses `GIT` or `WEBSITE`/`HTTP` values
  - `location` (string) — origin URL or repo path
  - `status` (string) — one of: `pending` | `ingesting` | `ready` | `failed`
  - `created_at` (RFC3339)
  - `last_updated` (RFC3339)
  - `last_error` (string, optional) — present when `status == "failed"`
  - `metadata` (map<string,string>, optional)
  - `tags` (repeated string, optional)
  - `extra` (map<string,string>, optional)

MCP Type Definitions (proto-like)
---------------------------------
This section gives the canonical shapes for implementors. Use the project's MCP IDL conventions to produce actual compiled types.

message ListSourcesRequest {
  // MVP: no filters. Returns the full registry snapshot (bounded by max_subagents).
}

message ListSourcesResponse {
  repeated SourceMetadata sources = 1;
  int32 total = 2;        // number of sources returned (0..max_subagents)
  int32 max_allowed = 3;  // equals configured orchestrator.max_subagents
}

message SourceMetadata {
  string subagent_id = 1;
  string name = 2;
  SourceType type = 3; // GIT | WEBSITE
  string location = 4;
  string status = 5;   // "pending" | "ingesting" | "ready" | "failed"
  string created_at = 6;
  string last_updated = 7;
  string last_error = 8; // optional
  map<string,string> metadata = 9;
  repeated string tags = 10;
  map<string,string> extra = 11;
}

enum SourceType {
  TYPE_UNKNOWN = 0;
  GIT = 1;
  WEBSITE = 2; // http/https
  OTHER = 3;   // reserved for future use, but not accepted by add_source in MVP
}

Operational rules (server-side)
-------------------------------
- Config and cap:
  - The orchestrator's configuration key `orchestrator.max_subagents` is authoritative and default is 20 for MVP.
  - The registry is bounded in practice by this cap; `list_sources` must return at most `max_subagents` entries.
- Selection:
  - `list_sources` returns every registered subagent regardless of status (`pending` / `ingesting` / `ready` / `failed`).
  - Each returned record must include `last_error` when a subagent's status is `failed`.
- Validation:
  - `add_source` must accept only `git` or `http(s)` (`SourceType` GIT/WEBSITE) in MVP and must reject other types with a validation error.
- Cap enforcement for `add_source`:
  - Count semantics: `current_count` counts all registered subagents (all statuses).
  - If `add_source` would create a new subagent and `(current_count + 1) > max_subagents`, the server MUST reject the request with an MCP-level error `MAX_SUBAGENTS_EXCEEDED`.
  - If `add_source` includes `source_id` and it matches an existing subagent, the call is treated as an update/reingest and does NOT increase the counted total; updates are allowed even when `current_count >= max_subagents`.
- `list_sources` ordering:
  - Default ordering should be `last_updated` descending (newest first). Ties must be broken deterministically (e.g., `created_at` asc, then `subagent_id` asc).
- Logging:
  - The system should still log ingestion failures, cap-rejection events, and other operational issues to a rolling log for operators. `list_sources` provides registry visibility; logs provide additional diagnostics (e.g., preserved artifacts location).

MCP error shape — cap rejection
-------------------------------
When `add_source` is rejected because adding would exceed `max_subagents`, return an MCP-level non-2xx error with a structured body, for example:

{
  "code": "MAX_SUBAGENTS_EXCEEDED",
  "message": "cannot add source: maximum number of subagents (20) reached",
  "current_count": 20,
  "max_subagents": 20
}

Suggested HTTP mapping for streamable deployments: 409 Conflict or 429 Too Many Requests — ensure the MCP client receives an error it can programmatically inspect.

Errors & Edge Cases
-------------------
- If more than `max_subagents` exist due to operator intervention (out-of-band), `list_sources` must still return the full registry but administrators should be notified; `add_source` must continue rejecting new additions until count ≤ max.
- Reingest/update with an existing `source_id` is allowed at cap and does not increase the registry count.
- `list_sources` may be slow if the registry is large, but the MVP cap keeps responses small and fast (<200ms target). Implementors should avoid expensive per-subagent runtime probes in this call.

Testing & Acceptance Criteria
-----------------------------
Minimal tests to include:

- Integration: `add_source` then `list_sources`
  - Start with empty state.
  - Call `add_source` for three small sources sequentially (blocking).
  - Each successful `add_source` must result in those subagents appearing in `list_sources`.
  - Validate `status` values and that `last_error` is present for failed ingestions.

- Cap enforcement:
  - Create `max_subagents` subagents. Verify that an additional `add_source` for a new `source_id` returns `MAX_SUBAGENTS_EXCEEDED` (MCP-level error).
  - Reingest with the same `source_id` when cap is reached — should succeed or fail depending on ingestion, but must not be rejected due to cap.

- Format conformance:
  - Ensure returned messages conform to the MCP/protobuf types used by the server.

- Ordering:
  - Create multiple subagents with controlled `last_updated` values and assert `list_sources` orders them newest-first; verify deterministic tie-break behavior.

Example responses
-----------------

Example successful `list_sources` response (MCP payload serialized to JSON):
{
  "sources": [
    {
      "subagent_id": "sa_012345",
      "name": "project-docs",
      "type": "GIT",
      "location": "https://github.com/org/repo",
      "status": "ready",
      "created_at": "2026-02-25T09:20:00Z",
      "last_updated": "2026-02-26T18:32:00Z",
      "last_error": "",
      "metadata": { "repo_url": "https://github.com/org/repo" },
      "tags": ["java","api"],
      "extra": {}
    },
    {
      "subagent_id": "sa_012346",
      "name": "site-docs",
      "type": "WEBSITE",
      "location": "https://example.com/docs",
      "status": "failed",
      "created_at": "2026-02-26T09:20:00Z",
      "last_updated": "2026-02-26T18:40:00Z",
      "last_error": "pdf-extraction failed: unsupported format",
      "metadata": { "crawl_depth": "1" }
    }
  ],
  "total": 2,
  "max_allowed": 20
}

Example `MAX_SUBAGENTS_EXCEEDED` error (MCP-level error body):
{
  "code": "MAX_SUBAGENTS_EXCEEDED",
  "message": "cannot add source: maximum number of subagents (20) reached",
  "current_count": 20,
  "max_subagents": 20
}

Notes & Rationale
-----------------
- Returning all registered subagents (including failed ones) gives immediate operator visibility via MCP and simplifies early debugging and CI assertions.
- Enforcing a configurable hard cap (`max_subagents`) keeps resource usage predictable in MVP and allows deterministic testing. The cap is enforced at `add_source` time and represented to callers as a structured MCP error so coding agents can react programmatically.
- Restricting accepted source types to `git` and `http(s)` reduces initial complexity while allowing easy extension of the `SourceType` enum in the future.
- `list_sources` intentionally avoids expensive runtime health probes; it is a snapshot of the orchestrator registry. Health-checking and deeper diagnostics are available via logs and operator tooling.

Next steps (optional)
---------------------
- If you want a formal proto IDL file for the MCP messages, I can produce `mcp/list_sources.proto` matching the shapes above.
- I can also produce unit/integration test stubs that assert cap enforcement, supported-type validation, and `list_sources` ordering if you'd like test scaffolding added to the repo.