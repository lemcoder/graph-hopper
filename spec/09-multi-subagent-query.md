# Multi-Subagent Query Orchestration Spec

## Purpose
Define the orchestration layer responsible for broadcasting a user's query to multiple subagents in parallel, executing independent LLM generation per subagent, evaluating confidence based on retrieved sources, and aggregating the results to return the single best answer.

## Key Decisions (MVP)

1. **Distributed Generation:** Instead of centralizing context and making one massive LLM call, each subagent operates independently. A subagent retrieves its own chunks, evaluates its confidence, and calls an LLM to generate an answer.
2. **Confidence-Based Selection:** The Orchestrator acts as a selector rather than a synthesizer. It collects answers and their associated confidence scores from all successful subagents, and strictly returns the result with the highest confidence score.
3. **Chunk-Derived Scoring:** The `confidence_score` is calculated prior to the LLM call using the `ConfidenceScorer` (from Spec 08). The subagent calculates the score for its retrieved chunks against the query. The maximum score among the retrieved chunks represents the subagent's overall confidence. This score is passed along with the final LLM-generated answer.
4. **Configurable LLMs via OpenRouter:** To optimize cost, latency, and flexibility, all LLM calls will be routed through **OpenRouter**. The system will use the `litellm` library to standardize the API calls across different model providers. Subagents can be configured to use a smaller, faster model (e.g., `openai/gpt-4o-mini` or `anthropic/claude-3-haiku`) strictly for reading chunks and extracting answers. The OpenRouter API key must be securely configurable (e.g., via environment variables).
5. **Concurrency with Asyncio:** Parallel execution is handled natively using Python's `asyncio` (`asyncio.gather`), enabling efficient non-blocking I/O across 10+ subagents simultaneously.
6. **Graceful Degradation:** Timeouts are configurable. If a subagent fails, throws an error, or exceeds the timeout threshold, the Orchestrator logs a warning, discards that subagent's execution, and proceeds with the successful responses.

## Architecture & Data Flow

### 1. Broadcast & Execution (Orchestrator)
- The Orchestrator receives a user `query`.
- It identifies all ready/active subagents.
- It uses `asyncio.gather` with `asyncio.wait_for` (applying the configured timeout) to trigger `subagent.aquery(query)` on all subagents concurrently.

### 2. Subagent Processing (Per Subagent)
- **Retrieval:** The subagent calls its `Retriever.retrieve_context(query)` to fetch the top-`k` chunks.
- **Scoring:** The subagent evaluates the retrieved chunks using the `ConfidenceScorer`. It calculates the score for each chunk and takes the `max()` score. This is the subagent's `confidence_score`.
  - *Note: If no chunks are retrieved, the confidence is 0.0 and the subagent can optionally short-circuit to return an empty response.*
- **Generation:** The subagent formats the retrieved chunks into XML (as defined in Spec 07) and constructs a prompt. It then calls `litellm.acompletion` using the configured OpenRouter model (e.g., `openrouter/openai/gpt-4o-mini`) and API key to generate an answer asynchronously.
- **Return:** The subagent returns a `SubagentResponse` containing the generated text, the `confidence_score`, and the list of source metadata.

### 3. Aggregation & Selection (Orchestrator)
- The Orchestrator awaits the `asyncio.gather` results.
- Exceptions (e.g., `asyncio.TimeoutError` or API failures) are caught, logged, and ignored.
- The list of successful `SubagentResponse` objects is sorted descending by `confidence_score`.
- The Orchestrator selects the response with the highest score and returns it to the user.

## Interface Definition

### Data Structures

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class SourceMetadata:
    doc_id: str
    url_or_path: str
    chunk_index: int

@dataclass
class SubagentResponse:
    subagent_id: str
    answer: str
    confidence_score: float
    sources: list[SourceMetadata]
```

### Subagent Interface

```python
class Subagent:
    # ... init, ingest, etc. ...

    async def aquery(self, query: str) -> SubagentResponse:
        """
        Retrieves context, scores it, generates an answer via LLM (using litellm + OpenRouter), 
        and returns the combined response.
        """
        pass
```

### Orchestrator Interface

```python
import asyncio
import logging

class Orchestrator:
    def __init__(self, subagents: list[Subagent], config: dict):
        self.subagents = subagents
        self.config = config
        self.logger = logging.getLogger(__name__)

    async def query_all(self, query: str) -> SubagentResponse | None:
        """
        Broadcasts the query to all subagents concurrently.
        Returns the single best SubagentResponse based on confidence_score.
        """
        timeout = self.config.get("subagent_timeout_seconds", 30.0)
        
        async def fetch(subagent: Subagent):
            try:
                return await asyncio.wait_for(subagent.aquery(query), timeout=timeout)
            except Exception as e:
                self.logger.warning(f"Subagent {subagent.subagent_id} failed or timed out: {e}")
                return None

        # Execute all subagent queries in parallel
        tasks = [fetch(sa) for sa in self.subagents]
        results = await asyncio.gather(*tasks)

        # Filter out None results (failures/timeouts)
        valid_results = [res for res in results if res is not None]

        if not valid_results:
            return None

        # Select the result with the highest confidence score
        best_result = max(valid_results, key=lambda x: x.confidence_score)
        
        return best_result
```

## Configuration Options

The system configuration file (e.g., `config.yaml` or a Pydantic settings class) must support the following parameters, with the API key securely managed (preferably loaded from an `OPENROUTER_API_KEY` environment variable):

```yaml
orchestrator:
  subagent_timeout_seconds: 15.0  # How long to wait before dropping a subagent's query
  
llm:
  provider: "openrouter"
  api_key: "${OPENROUTER_API_KEY}"  # Should be securely injected
  
  # Used by subagents to read chunks and extract answers.
  # LiteLLM allows using the openrouter/ prefix to route requests correctly.
  subagent_model: "openrouter/openai/gpt-4o-mini" 
  
  # Used by higher-level reasoning or the orchestrator itself if synthesis is added later
  orchestrator_model: "openrouter/openai/gpt-4o" 
```

## Success Criteria
- **Parallelism:** Orchestrator successfully runs 10+ subagent queries concurrently without blocking the main event loop.
- **Accuracy:** The system reliably returns the `SubagentResponse` with the highest `confidence_score`.
- **Resilience:** If one subagent LLM call hangs or a local vector search crashes, the other subagents complete successfully, and the orchestrator returns the best available answer.
- **Model Routing:** Subagents correctly utilize the `litellm` integration with OpenRouter to hit the `subagent_model` configuration, enabling cost savings over using the primary expensive model for every parallel read operation.