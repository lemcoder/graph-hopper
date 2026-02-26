# MCP Server Layer Spec

## Purpose
Expose ERKS via MCP protocol with three tools: add_source, query, list_sources.

## Requirements
- Implement MCP server (FastAPI or similar).
- Tool: add_source({name, type, location}) → {subagent_id, status}
- Tool: query({query}) → {answer, sources, confidence}
- Tool: list_sources() → [{subagent_id, name, type, status}]
- Block add_source until ingestion completes.
- Return errors for invalid requests.

## Success Criteria
- All tools available via HTTP.
- Responses match schema.
- Handles ≥10 concurrent subagents.
