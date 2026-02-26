# Expert Runtime Knowledge System (ERKS)

## High-Level Specification v0.1

---

# 1. Overview

The Expert Runtime Knowledge System (ERKS) is an embeddable, MCP-native knowledge runtime that dynamically ingests external sources (websites, repositories, documents) and exposes them as isolated "Expert Agents" capable of answering queries using retrieval-augmented generation (RAG).

The system is designed to support coding agents and other AI systems by providing real-time, source-grounded expertise generated on demand.

ERKS must support:

* Dynamic knowledge ingestion at runtime
* Semantic retrieval via embeddings
* Knowledge graph construction
* Expert isolation per source
* MCP-compatible interface
* Embeddable runtime core (C++ target, Python prototype)

---

# 2. Goals

## 2.1 Primary Goals

* Dynamically create "Expert Agents" from arbitrary sources
* Provide fast semantic retrieval from ingested knowledge
* Expose system functionality via MCP protocol
* Support coding agents as primary clients
* Operate locally or embedded without external infrastructure

## 2.2 Secondary Goals

* Enable progressive ingestion (expert usable immediately)
* Support hybrid vector + graph retrieval
* Allow multi-expert orchestration
* Provide deterministic and reproducible retrieval

---

# 3. Non-Goals (MVP)

The following are explicitly out of scope for MVP:

* Distributed multi-node deployment
* GUI interface
* Authentication or multi-tenant isolation
* Perfect knowledge graph extraction
* Full symbolic reasoning engine

---

# 4. Definitions

## Subagent

A subagent is an isolated runtime knowledge unit derived from a single logical source. Each subagent is strictly tied to one source (e.g., a website, repository, or document) and cannot combine multiple sources.

Examples:

* WebsiteSubagent("docs.example.com")
* GitRepoSubagent("github.com/org/repo")
* DocsSubagent("/local/docs")

Each subagent maintains independent:

* vector index
* knowledge graph
* metadata store
* retrieval pipeline

Throughout this document, "subagent" replaces the previous term "Expert Agent" for clarity and consistency.

---

## Knowledge Source

A Knowledge Source is any ingestible content location.

Supported types:

* Website
* Git repository
* Local directory
* PDF / documents
* API endpoint

Each subagent is strictly single-source; multi-source subagents are not supported.

---

## Chunk

Smallest retrieval unit.

Structure:

```
Chunk {
  id: string
  text: string
  embedding: vector<float>
  metadata: map<string, string>
}
```

---

# 5. System Architecture

---

## 5.1 Subagent Orchestration Logic

- Each subagent is conceptualized as a small LLM agent sitting atop its own knowledge graph and vector index, capable of answering questions based solely on its single source.
- Subagents act as “friends” in a “Who Wants to Be a Millionaire” scenario: the main system (coding agent) asks a question, and each subagent responds with an answer and a confidence score.
- The orchestrator collects all answers, compares confidence scores, and returns the highest-confidence answer to the coding agent.
- When a query arrives, the orchestrator routes it to all active subagents in parallel.
- Each subagent generates an answer and a confidence score using a standard formula (cosine similarity + keywords).
- The orchestrator selects the answer with the highest confidence and returns it to the client.
- For MVP, this mechanism is simple: round-robin all subagents, parallel answer generation, pick highest confidence.

---

## 5.2 Dynamic Source Ingestion

- The system must support appending new sources at runtime via the MCP interface.
- Upon ingestion, a new subagent is initialized and added to the orchestrator’s pool.
- Subagents are only available for queries once ingestion is 100% complete; no partial answers are allowed for simplicity.
- Example: Coding agent requests Java documentation as a new source. The orchestrator downloads the content, builds a knowledge graph/vector index, and spins up a new subagent for that source. After initialization, queries can be routed to this new subagent alongside existing ones.

---

## 5.3 Example Scenario

```
Coding Agent → MCP Server → Orchestrator
→ [Subagent(JavaDocs), Subagent(PythonDocs), Subagent(StackOverflow)]
→ Each subagent answers with confidence
→ Orchestrator picks highest confidence
→ Returns answer to Coding Agent
```

## 5.4 High-Level Architecture

```
Client (Coding Agent)
        │
        ▼
    MCP Server Layer
        │
        ▼
 Expert Orchestrator
   │      │      │
   ▼      ▼      ▼
Expert  Expert  Expert
Agent   Agent   Agent
   │
   ▼
Vector Index + Knowledge Graph
```

---

## 5.5 Core Components

### 5.5.1 MCP Server Layer

Responsibilities:

* Expose MCP tools
* Handle requests from clients
* Route queries to orchestrator

Required tools:

* add_source
* query
* list_sources

Only these three tools are required for MVP. `add_source` creates a new subagent, `query` routes a question to all subagents and returns the highest-confidence answer, and `list_sources` returns all active sources/subagents.

---

### 5.5.2 Subagent Orchestrator

Responsibilities:

* Create subagents
* Destroy subagents
* Route queries to all subagents (round-robin for MVP)
* Aggregate responses

Interface:

```
add_source(source_config) → subagent_id
query(query_string) → response
list_sources() → source_list
```

---

### 5.5.3 Subagent

Responsibilities:

* Ingest source content
* Generate embeddings
* Build vector index
* Build knowledge graph (included in MVP)
* Perform retrieval
* Generate context

Internal components:

```
Subagent {
  DataSource
  ChunkStore
  EmbeddingModel
  VectorIndex
  KnowledgeGraph
  Retriever
}
```

---

### 5.5.4 Data Ingestion Pipeline

Pipeline stages:

1. Fetch content
2. Parse content
3. Chunk content
4. Generate embeddings
5. Insert into index
6. Update knowledge graph

Subagents are only available for queries after ingestion is 100% complete.

---

### 5.5.5 Embedding Model

Responsibilities:

* Convert text to semantic vectors

Requirements:

* Local model support
* Batch embedding capability
* Deterministic outputs

MVP model recommendation:

* BGE-small-en-v1.5

Confidence scoring for retrieval uses a standard formula: cosine similarity plus keyword presence.

---

### 5.5.6 Vector Index

Responsibilities:

* Store embeddings
* Perform nearest neighbor search

Required operations:

```
add(vector, chunk_id)
search(query_vector, k)
remove(chunk_id)
```

Performance targets:

* Query latency: < 100 ms
* Insert latency: < 5 ms per chunk

---

### 5.5.7 Knowledge Graph

Responsibilities:

* Store relationships between entities

Example relationships:

* class → defined_in → file
* function → calls → function
* module → imports → module

Knowledge graph construction is included in MVP unless it adds prohibitive complexity.

---

### 5.5.8 Retriever

Responsibilities:

* Convert query to embedding
* Retrieve relevant chunks
* Assemble context

Pipeline:

```
query → embedding → vector search → context assembly
```

---

# 6. MCP Interface Specification

## Tool: add_source

Creates new subagent.

Arguments:

```
{
  name: string
  type: string
  location: string
}
```

Returns:

```
{
  subagent_id: string
  status: string
}
```

---

## Tool: query

Queries all subagents and returns the highest-confidence answer.

Arguments:

```
{
  query: string
}
```

Returns:

```
{
  answer: string
  sources: list
  confidence: float
}
```

---

## Tool: list_sources

Returns all sources/subagents.

---

# 7. Runtime Behavior

## 7.1 Expert Creation Flow

```
User request
→ create expert
→ initialize empty expert
→ begin background ingestion
→ expert usable after set up 100%
→ ingestion completes asynchronously
```

---

## 7.2 Query Flow

```
User query
→ MCP server
→ orchestrator
→ expert agent
→ embedding generation
→ vector search
→ context assembly
→ return context
→ LLM generates answer
```

---

# 8. Performance Requirements

MVP targets:

Expert usable:

* < 5 seconds

Query latency:

* < 500 ms

Memory usage per expert:

* < 500 MB

Concurrent experts supported:

* ≥ 10

# 9. Success Criteria

MVP considered successful when:

* Coding agent can dynamically ingest website
* Subagent created in < 10 seconds
* Subagent can answer queries correctly (ideally grounded in source chunks; correctness benchmarks are desirable if available)
* System accessible via MCP
* Multiple subagents can coexist
