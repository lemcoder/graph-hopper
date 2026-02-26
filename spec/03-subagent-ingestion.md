# Subagent Lifecycle & Ingestion Spec

## Purpose
Create subagent and ingest source content.

## Requirements
- Fetch content from location (website, repo, file).
- Parse and chunk content.
- Generate embeddings.
- Build vector index and knowledge graph.
- Mark subagent as ready only after ingestion completes.

## Success Criteria
- Subagent ready <10s after add_source.
- Ingestion errors reported.
- Subagent only queryable when ready.
