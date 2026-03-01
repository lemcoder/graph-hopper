# Testing & Validation Spec

## Purpose
Ensure the functional correctness, reliability, and determinism of ingestion, querying, scoring, and orchestration pipelines for the MVP.

## Requirements & Scope
- **Code Coverage:** Maintain a minimum of **90%** code coverage.
- **Core Workflows Tested:** 
  - `add_source` (document parsing, chunking, and storage)
  - `query` (context retrieval and generation)
  - `list_sources`
  - Confidence scoring and ranking logic
- **Performance:** Explicit performance targets (ingestion time, query latency, memory) are intentionally excluded for the MVP phase. The primary focus is functional correctness.

## Testing Strategy
- **Framework:** `pytest` managed via `uv`.
- **Mocking External Dependencies:** All external LLM calls and third-party API requests must be mocked to guarantee deterministic tests, eliminate network latency, and avoid API costs.
- **Databases:** Tests must use an **in-memory database** (for both vector and graph storage) to ensure fast execution and strict isolation. Database state should be wiped clean between test runs.

## Test Data: "Golden Fixtures"
To reliably evaluate ingestion and confidence scoring, a standardized set of synthetic test data ("Golden Fixtures") will be maintained (e.g., in a `tests/fixtures/` directory).
- *Implementation Note:* Since real-world data is unavailable for now, we will create manually crafted dummy documents (e.g., sample markdown text with clear, indisputable facts, and predefined expected graph relationships). These fixtures will serve as the ground truth for validation tests.

## CI/CD Integration
Automated testing is governed by the `.github/workflows/tests.yml` GitHub Actions workflow.
- Triggers on Pull Requests and workflow dispatches.
- Provisions a Python 3.11 environment using `uv`.
- Automatically executes the `pytest` suite to gate merges.

## Success Criteria
- Test coverage `>= 90%`.
- All tests pass in the CI pipeline.
- Fully deterministic, reproducible test results (zero flaky tests caused by live API constraints or persistent database state leakage).