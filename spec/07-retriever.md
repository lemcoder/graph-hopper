# Retriever Logic Spec

## Purpose
Retrieve relevant chunks and assemble context.

## Requirements
- Convert query to embedding.
- Search vector index for top-k chunks.
- Optionally use knowledge graph for context expansion.
- Assemble context for answer generation.

## Success Criteria
- Retriever returns relevant chunks for queries.
- Context assembly is deterministic.
- Retrieval latency <100ms.
