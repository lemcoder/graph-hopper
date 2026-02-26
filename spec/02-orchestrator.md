# Subagent Orchestrator Spec

## Purpose
Manage subagent lifecycle and query routing.

## Requirements
- Create/destroy subagents.
- Route queries to all subagents in parallel.
- Aggregate answers and confidences.
- Select highest-confidence answer.
- Provide interface: add_source, query, list_sources.

## Success Criteria
- Orchestrator manages ≥10 subagents.
- Query returns best answer within 500ms.
- Handles subagent failures gracefully.
