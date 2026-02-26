# Source Listing & Metadata Spec

## Purpose
List all active subagents and their metadata.

## Requirements
- Implement list_sources tool.
- Return: [{subagent_id, name, type, status, size, last_updated}]
- Include ingestion status and metadata.

## Success Criteria
- Accurate list of all subagents.
- Metadata reflects current state.
- Supports ≥10 subagents.
