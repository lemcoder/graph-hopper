# Retriever Logic Spec

## Purpose
Define the system that takes a coding agent's query, retrieves the most relevant semantic chunks from the local vector index, and assembles them into a structured context window for LLM consumption.

## Key Decisions (MVP)

1. **Stateless Service Architecture:** The Retriever is designed as a stateless service. It receives its dependencies (`EmbeddingInterface` and `VectorStore`) via dependency injection.
2. **Contextual Agent Queries:** We assume the upstream "user" is an intelligent coding agent capable of generating contextually relevant queries. Therefore, conversational query rewriting (e.g., resolving pronouns from chat history) is out of scope. The Retriever processes the raw query string exactly as provided.
3. **Relevance-Based Ordering:** Retrieved chunks will be sorted and presented to the LLM purely based on their similarity score (most relevant first, descending order), rather than grouped by document or chronological chunk order.
4. **XML Formatting:** Context will be assembled using explicit XML tags (e.g., `<document>`, `<chunk>`). This provides clear boundary markers for the LLM to distinguish between different sources and actual prompt instructions.
5. **Knowledge Graph (Deferred):** Graph-based context expansion and hybrid search are explicitly deferred and out of scope for the MVP. The initial focus is strictly on dense vector retrieval.
6. **No Strict Thresholding (Yet):** For the MVP, the system will return the top-`k` results regardless of how low the similarity score is. However, the interface and logic must be structured to easily accommodate a minimum similarity score threshold in the future.

## Architecture & Data Flow

### 1. Query Embedding
- The Retriever receives a text `query` and a target `k` (default: 5).
- It calls `embedder.embed([query])` to generate a single dense vector representation of the query.

### 2. Vector Search
- The Retriever passes the query vector to `vector_store.search(query_vector, k=k)`.
- The `VectorStore` returns a list of `(Chunk, similarity_score)` tuples.

### 3. Context Assembly & Formatting
- The Retriever iterates over the returned tuples.
- *(Future capability placeholder: Here is where similarity scores would be evaluated against a threshold).*
- Each `Chunk` is formatted into an XML block containing its metadata (`doc_id`, `url_or_path`, and `score`) and its raw `text`.
- The formatted blocks are concatenated into a single string to be injected into the LLM's prompt.

## Interface Definition

```python
class Retriever:
    def __init__(self, embedder: EmbeddingInterface, vector_store: VectorStore):
        self.embedder = embedder
        self.vector_store = vector_store

    def retrieve_context(self, query: str, k: int = 5) -> str:
        """
        Embeds the query, searches the vector store, and formats the results as an XML string.
        """
        # 1. Embed query
        # query_vector = self.embedder.embed([query])[0]
        
        # 2. Search index
        # results = self.vector_store.search(query_vector, k=k)
        
        # 3. Assemble and return XML
        pass
```

## Context Formatting (XML)

The assembled output string returned by `retrieve_context` should look like this:

```xml
<context>
  <document source="path/to/file.py" doc_id="123" relevance_score="0.89">
    <chunk>
      def hello_world():
          print("Hello, world!")
    </chunk>
  </document>
  <document source="path/to/other_file.py" doc_id="456" relevance_score="0.75">
    <chunk>
      # This is another relevant piece of code
      class MyClass:
          pass
    </chunk>
  </document>
</context>
```

## Success Criteria
- **Latency:** End-to-end retrieval (embedding query + FAISS search + string assembly) completes in `< 100ms`.
- **Determinism:** Given a deterministic embedder and a stable vector store, identical queries must consistently produce identical assembled XML strings.
- **Robustness:** The retriever handles empty vector stores gracefully (returning an empty `<context></context>` block) and does not crash if the store contains fewer than `k` chunks.