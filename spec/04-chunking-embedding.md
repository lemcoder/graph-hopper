# Chunking & Embedding Spec

## Purpose
Convert extracted source content into text chunks and generate vector embeddings using a local embedding model. For the MVP, we prioritize high-speed, local inference using the `fastembed` library with a straightforward token-window chunking strategy.

## Key Decisions (MVP)
1. **Embedding Library**: Use `fastembed` to run `BGE-small-en-v1.5` (or the configured model) locally. This is highly optimized for ONNX models and fast CPU inference.
2. **Chunking Strategy**: Token-window chunking only. Target size 500 tokens, 50 token overlap, minimum 64 tokens. Structural/semantic chunking is deferred for future iterations.
3. **Tokenizer**: Use the exact tokenizer tied to the target embedding model (`BGE-small-en-v1.5`) to count and split tokens accurately.
4. **Data Structures**: Keep `Chunk` metadata and dense vector embeddings parallel for memory efficiency (e.g., `IngestionResult(chunks, embeddings)`), rather than embedding the vector directly into the chunk object. 
5. **Serialization**: The `Chunk` object is structured as a dataclass with explicit `to_dict()` and `from_dict()` methods to make JSON serialization to disk seamless.
6. **Batching**: Entire documents are chunked into memory as a list of `Chunk` objects first, then embeddings are generated in batches using `embedding_batch_size` (default 64).

## Data Structures
Reflecting the existing code in `erks/subagent/ingestion.py`:

### `Chunk`
Represents a fragment of text and its provenance. Built as a dataclass to enable easy JSON serialization when persisted by the Vector Store.
```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class Chunk:
    text: str
    doc_id: str
    chunk_index: int
    url_or_path: str = ""
    token_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializes the Chunk to a dictionary for JSON storage."""
        return {
            "text": self.text,
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "url_or_path": self.url_or_path,
            "token_count": self.token_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chunk":
        """Deserializes a dictionary into a Chunk object."""
        return cls(**data)
```

### `IngestionResult`
Keeps chunks and embeddings parallel for efficient downstream processing.
```python
from dataclasses import dataclass

@dataclass
class IngestionResult:
    chunks: list[Chunk]
    embeddings: list[list[float]]
```

## Chunking Logic (Token Window)
The chunking process operates per-document:
1. Extract plain text from the source document.
2. Tokenize the full text using the model's native tokenizer.
3. Slide a window over the tokens:
   - **Target size**: 500 tokens.
   - **Overlap**: 50 tokens with the previous chunk.
   - **Minimum size**: 64 tokens. If the final chunk of a document has fewer than 64 tokens, merge it into the previous chunk (if one exists) or discard it if the document is trivial.
4. Decode each token window back to a string to form the `text` of the `Chunk`.
5. Assign a sequential `chunk_index` starting from 0.
6. Accumulate all `Chunk` objects into a single list for the document/source.

## Embedding Implementation
We implement the existing `EmbeddingInterface` defined in `erks/subagent/ingestion.py`:

```python
from typing import Protocol

class EmbeddingInterface(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

### `FastEmbedder` (Production)
- Initializes the `fastembed.TextEmbedding` model.
- Uses `config.orchestrator.default_embedding_model` (e.g., `"BAAI/bge-small-en-v1.5"`).
- Uses `config.orchestrator.embedding_batch_size` (e.g., 64) during the `embed` call by passing it to the library's batch generator.
- Returns a list of floats (dense vectors) mapping 1:1 to the `texts` input.

### `DeterministicEmbedder` (Testing)
- The existing `DeterministicEmbedder` class using SHA-256 in `erks/subagent/ingestion.py` must remain the default for all automated tests.
- This ensures reproducible vectors, stable test environments, and deterministic tie-breaking without downloading large model weights during unit tests.

## Success Criteria
- **Latency**: Embedding generation takes `< 5ms` per chunk on standard CPU hardware (facilitated by `fastembed` ONNX execution).
- **Safety**: All text content is safely chunked without triggering maximum sequence length / token limit exceptions from the embedding model.
- **Reproducibility**: `DeterministicEmbedder` guarantees the exact same output for the exact same input during test runs.
- **Memory Efficiency**: Keeping chunks and embeddings as parallel lists prevents object bloat and neatly matches the indexing patterns expected by vector stores (like FAISS).