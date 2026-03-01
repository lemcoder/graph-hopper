# Vector Index Spec

## Purpose
Provide a highly efficient, local, in-process vector storage and retrieval mechanism for a single Subagent's chunk embeddings. It pairs dense vector representations with their corresponding metadata to enable grounded query responses.

## Key Decisions (MVP)

1. **Library Selection:** FAISS (`faiss-cpu`) is used for the vector index. It provides fast, local, and in-memory nearest neighbor search that perfectly aligns with the parallel lists data structure (`IngestionResult`) emitted by the chunking and embedding pipeline.
2. **Persistence Strategy:** Subagent data is split into two files stored within the subagent's dedicated directory on disk:
   - `index.faiss`: The binary serialized FAISS index.
   - `chunks.json`: A JSON file containing the serialized list of `Chunk` metadata objects.
3. **Index Lifecycle (Drop & Rebuild):** Because each Subagent encapsulates a single knowledge source (e.g., one git repo or website), we do not implement complex, piecemeal `remove(chunk_id)` or update operations. On re-ingestion, the system simply drops the existing `index.faiss` and `chunks.json` files and rebuilds the index from scratch.
4. **Dimensions & Distance Metric:** Default to `384` dimensions to match `BGE-small-en-v1.5`. The distance metric defaults to Inner Product (`IndexFlatIP`). To achieve Cosine Similarity (which `fastembed` models typically expect), vectors must be L2-normalized before being added to or searched in the index. These parameters should be configurable via the orchestrator config.

## Architecture & Data Flow

### 1. Ingestion / Build Phase
- Receives an `IngestionResult` containing `chunks` (list of `Chunk` objects) and `embeddings` (list of float arrays).
- **Initialization:** Creates a FAISS `IndexFlatIP` with the configured dimensions.
- **Normalization:** L2-normalizes the dense vectors.
- **Insertion:** Adds vectors to the FAISS index. FAISS implicitly assigns sequential integer IDs (0 to N-1) corresponding to the list order.
- **Persistence:** 
  - Writes the index to `storage.base_path/<subagent_id>/index.faiss` using `faiss.write_index`.
  - Serializes the `chunks` list to `storage.base_path/<subagent_id>/chunks.json`.

### 2. Search Phase
- **Query Prep:** Takes a generated embedding for the user's query and L2-normalizes it.
- **Execution:** Performs a FAISS `search(query_vector, k)` to retrieve the top-`k` nearest neighbor distances and their corresponding integer IDs.
- **Rehydration:** Uses the returned integer IDs to look up the exact `Chunk` objects from the in-memory `chunks` list (loaded from `chunks.json`).
- **Return:** Yields a list of `(Chunk, distance)` tuples to the answer generator.

### 3. Re-ingestion / Deletion Phase
- When a `source_id` is re-ingested or a subagent is deleted, the system deletes the `index.faiss` and `chunks.json` files (or the entire subagent directory) and starts the ingestion pipeline anew.

## Interface Definition

The Vector Store abstraction should fulfill operations similar to this:

```python
class VectorStore:
    def __init__(self, subagent_dir: str, dimensions: int = 384):
        self.subagent_dir = subagent_dir
        self.dimensions = dimensions
        self.index = None
        self.chunks: list[Chunk] = []

    def build(self, embeddings: list[list[float]], chunks: list[Chunk]) -> None:
        """Normalizes vectors, builds the FAISS index, and persists to disk alongside chunks.json."""
        pass

    def load(self) -> None:
        """Loads index.faiss and chunks.json from disk into memory."""
        pass

    def search(self, query_vector: list[float], k: int = 5) -> list[tuple[Chunk, float]]:
        """Normalizes the query, searches FAISS, and maps IDs back to Chunk objects."""
        pass

    def drop(self) -> None:
        """Deletes the persisted index and metadata from disk."""
        pass
```

## Determinism & Testing
- To satisfy MVP determinism requirements (as defined in `00-scope.md`), the vector index must be entirely predictable during testing.
- Tests will use the `DeterministicEmbedder` (which outputs stable SHA-based vectors). The FAISS index must consistently return the same top-`k` results and distance scores for these stable vectors across multiple test runs.
- Tie-breaking logic: If FAISS returns identical similarity scores for multiple chunks, the retrieval layer should sort them deterministically by chunk index or ID to avoid flaky tests.

## Success Criteria
- **Latency:** Vector search (`search` operation) completes in `< 100ms` for up to 10,000 chunks.
- **Reliability:** Drop-and-rebuild semantics work cleanly without resource leaks, dangling file handles, or out-of-memory errors on repeated ingestions.
- **Data Integrity:** The sequence of chunks in `chunks.json` perfectly matches the integer IDs inside `index.faiss`, ensuring the correct text is retrieved for a given nearest-neighbor vector.