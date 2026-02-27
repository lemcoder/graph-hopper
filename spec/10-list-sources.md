# Source Listing & Metadata Spec (v0.2)

Purpose
-------
This document specifies the `list_sources` MCP tool for the Expert Runtime Knowledge System (ERKS). It is an MVP-focused, constrained listing API that returns only subagents that are fully ingested and healthy. Broken or unhealthy subagents must not be returned; instead they are recorded to an on-disk log for operator inspection.

Goals & Constraints
-------------------
- The MCP server exposes a `list_sources` tool that returns up to 20 ready subagents.
- Only `ready` and healthy subagents are returned. Subagents failing health checks are excluded and logged.
- There is no pagination; a hard upper bound of 20 entries exists (see `MAX_LIST_SOURCES = 20`).
- `add_source` is synchronous for the caller (it blocks until ingestion completes), therefore `list_sources` will only ever see completed subagents.
- The server uses MCP types (protobuf-style) for the tool request/response.

High-level semantics
--------------------
- Clients call `list_sources` to obtain a snapshot of all available subagents that are acceptable for query routing.
- Returned subagents are guaranteed usable by the orchestrator (i.e., `ready` + healthy).
- Any subagent that fails runtime health checks, or whose ingestion completed with errors, must not appear in the response; the server appends an entry describing the problem to a log file at `logs/subagent_errors.log`.

What `list_sources` returns
---------------------------
- A bounded list (<= 20) of `SourceMetadata` records. Each record contains stable identifiers, source type, t-shirt size estimate, timestamps, and optional free-form metadata.
- The minimal canonical fields are:
  - `subagent_id` (string) — stable unique id
  - `name` (string)
  - `type` (enum) — one of: `WEBSITE`, `GIT`, `LOCAL`, `PDF`, `API`, `OTHER`
  - `status` (string) — always `"ready"` for any returned item
  - `size` (SizeEstimate) — t-shirt estimate and optional estimated bytes
  - `created_at` (RFC3339)
  - `last_updated` (RFC3339)
  - `metadata` (map<string,string>) — backend-provided source metadata (e.g., repo URL)
  - `tags` (repeated string) — optional
  - `extra` (map<string,string>) — extensibility for implementors

MCP Type Definitions (proto-like)
---------------------------------
The server must expose MCP-compatible types. Below is the canonical schema expressed in protobuf-like notation for implementors. Use the project's MCP IDL conventions to produce actual compiled types.

message ListSourcesRequest {
  // No filter fields: MVP returns all ready+healthy subagents up to MAX_LIST_SOURCES.
  // Future filters are out-of-scope for MVP.
}

message ListSourcesResponse {
  repeated SourceMetadata sources = 1;
  // total is the number of sources returned (0..MAX_LIST_SOURCES). No server-side total-of-all-sources is maintained.
  int32 total = 2;
  // max_allowed always equals 20 in this MVP.
  int32 max_allowed = 3;
}

message SourceMetadata {
  string subagent_id = 1;
  string name = 2;
  SourceType type = 3;
  string status = 4; // ALWAYS "ready" for returned records
  SizeEstimate size = 5;
  string created_at = 6; // RFC3339
  string last_updated = 7; // RFC3339
  map<string, string> metadata = 8;
  repeated string tags = 9;
  map<string, string> extra = 10;
}

message SizeEstimate {
  Tshirt tshirt = 1;            // coarse capacity estimate
  int64 estimated_bytes = 2;    // optional; -1 if unknown
}

enum Tshirt {
  T_UNKNOWN = 0;
  T_S = 1;
  T_M = 2;
  T_L = 3;
  T_XL = 4;
}

enum SourceType {
  TYPE_UNKNOWN = 0;
  WEBSITE = 1;
  GIT = 2;
  LOCAL = 3;
  PDF = 4;
  API = 5;
  OTHER = 6;
}

Operational rules (server-side)
-------------------------------
- Hard limit:
  - MAX_LIST_SOURCES = 20. The server must never return more than 20 SourceMetadata entries.
- Selection:
  - Only include subagents whose ingestion completed successfully and whose runtime health check passes.
  - Health check is an implementation detail; minimally it must confirm:
    - The vector index is reachable.
    - The subagent's retriever responds to a lightweight probe.
  - Subagents whose ingestion completed with warnings/errors or fail health checks must be omitted and logged.
- Logging:
  - Errors and unhealthy statuses are appended to `logs/subagent_errors.log` with a timestamp and the `subagent_id`.
  - Logged entry format (one JSON object per line) example:
    { "ts":"2026-02-27T12:00:00Z", "subagent_id":"sa_01", "phase":"health_check", "error":"index unreachable" }
- Visibility:
  - All subagents are considered visible; there is no per-source privacy flag in the MVP.
- add_source semantics:
  - `add_source` is synchronous and blocks until ingestion finishes successfully (or fails). Because of this, `list_sources` will never observe partial / ingesting subagents.
  - If `add_source` fails, the failed subagent is not created; the error is logged to `logs/subagent_errors.log`.

Behavioral guarantees
---------------------
- Consistency model:
  - Strong consistency at the call boundaries: once `add_source` returns success, subsequent `list_sources` calls must reflect the new subagent (subject to the MAX_LIST_SOURCES cap).
- Ordering:
  - `list_sources` may return sources in any stable order; implementors should return newest `last_updated` first when possible.
- Performance:
  - The `list_sources` response should be fast (typical target < 200ms). The response set is small (≤20) so the server should avoid expensive runtime metrics lookups.

Errors & Edge Cases
-------------------
- The `list_sources` MCP tool has a simple success/failure model:
  - On success, return `ListSourcesResponse` with `total` and `sources`.
  - On server error, return an MCP-level error (5xx). Partial success is not applicable: either the call returns the current ready set or an error.
- If more than 20 ready subagents exist, the server returns the 20 most-recently-updated (by `last_updated`) ready+healthy subagents and sets `total` to 20.

Testing & Acceptance Criteria
-----------------------------
Minimal tests to include in the project test suite:

- Integration: `add_source` then `list_sources`:
  - Start with empty state.
  - Call `add_source` for three small sources sequentially (blocking).
  - Each successful `add_source` must result in those subagents appearing in `list_sources`.
  - Validate `status == "ready"` and `size.tshirt` is non-UNKNOWN.

- Health exclusion:
  - Simulate subagent whose index is down; ensure it is not returned by `list_sources`.
  - Confirm an appropriate JSON log line is appended to `logs/subagent_errors.log`.

- MAX cap:
  - Create 25 ready subagents. `list_sources` must return 20 entries and `total == 20`. Confirm ordering preference (most recent by `last_updated`) is honored.

- Format conformance:
  - Ensure returned messages match the MCP/protobuf types used by the server.

Example JSON response (MCP payload serialized to JSON)
------------------------------------------------------
{
  "sources": [
    {
      "subagent_id": "sa_012345",
      "name": "project-docs",
      "type": "GIT",
      "status": "ready",
      "size": { "tshirt": "T_M", "estimated_bytes": 250000 },
      "created_at": "2026-02-25T09:20:00Z",
      "last_updated": "2026-02-26T18:32:00Z",
      "metadata": { "repo_url": "https://github.com/org/repo" },
      "tags": ["java","api"],
      "extra": {}
    }
  ],
  "total": 1,
  "max_allowed": 20
}

Notes & Rationale
-----------------
- The user requested only ready agents be visible. To satisfy that and keep the client simple, `add_source` blocks until ingestion is finished; therefore `list_sources` needs only to deal with completed and healthy subagents.
- Coarse `SizeEstimate` (t-shirt) is used instead of mandatory byte-accurate size to avoid expensive size computation and to match the user's preference for estimations.
- No pagination or filters for the MVP simplifies implementation. The hard cap of 20 enforces bounded responses.
- Health/metrics are intentionally excluded from the response: unhealthy agents are omitted and errors are logged to file as requested.

Next steps I can take for you
-----------------------------
- Produce a formal MCP/protobuf IDL file for the messages above if you want canonical compiled types.
- Add unit test stubs for the integration tests described.
- Implement or review a sample server handler that enforces `MAX_LIST_SOURCES` and the health-check filtering.

If you want the protobuf IDL now, tell me and I will emit an `mcp/list_sources.proto` draft using the canonical field numbers shown above.