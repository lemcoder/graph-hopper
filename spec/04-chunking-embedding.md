# Chunking & Embedding Spec

## Purpose
Convert source content to chunks and generate embeddings.

## Requirements
- Define Chunk: {id, text, embedding, metadata}.
- Implement chunking logic (text, code, docs).
- Integrate local embedding model (BGE-small-en-v1.5).
- Batch embedding for efficiency.

## Success Criteria
- Chunks created for all content.
- Embeddings deterministic and reproducible.
- Embedding latency <5ms per chunk.
