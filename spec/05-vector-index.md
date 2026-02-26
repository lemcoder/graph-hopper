# Vector Index Spec

## Purpose
Store and search chunk embeddings.

## Requirements
- Implement vector index (FAISS/HNSWlib).
- Operations: add(vector, chunk_id), search(query_vector, k), remove(chunk_id).
- Support nearest neighbor search.

## Success Criteria
- Query latency <100ms.
- Index supports ≥10,000 chunks.
- Remove operation works reliably.
