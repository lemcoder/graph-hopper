# Multi-Subagent Query Orchestration Spec

## Purpose
Query all subagents in parallel and aggregate answers.

## Requirements
- Broadcast query to all ready subagents.
- Collect answers and confidence scores.
- Select answer with highest confidence.
- Return answer, sources, confidence.

## Success Criteria
- Parallel querying works for ≥10 subagents.
- Aggregation returns best answer.
- Handles subagent timeouts/errors gracefully.
