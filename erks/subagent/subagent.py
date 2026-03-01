"""Subagent: per-source retrieval + LLM answer generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from erks.subagent.confidence import ConfidenceScorer
from erks.subagent.retriever import Retriever


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SourceMetadata:
    """Provenance for a single retrieved chunk."""

    doc_id: str
    url_or_path: str
    chunk_index: int


@dataclass
class SubagentResponse:
    """Answer produced by a single subagent."""

    subagent_id: str
    answer: str
    confidence_score: float
    sources: list[SourceMetadata] = field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM abstraction
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMInterface(Protocol):
    async def complete(self, context: str, query: str) -> str: ...


class MockLLM:
    """Deterministic stub used in tests – no network calls."""

    def __init__(self, response: str = "mock answer"):
        self._response = response

    async def complete(self, context: str, query: str) -> str:  # noqa: ARG002
        return self._response


class LiteLLM:
    """Production LLM backed by litellm / OpenRouter."""

    def __init__(self, model: str, api_key: str = ""):
        self._model = model
        self._api_key = api_key

    async def complete(self, context: str, query: str) -> str:
        import litellm  # type: ignore

        messages = [{"role": "user", "content": f"{context}\n\nQuery: {query}"}]
        kwargs: dict = {"model": self._model, "messages": messages}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        response = await litellm.acompletion(**kwargs)
        return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Subagent
# ---------------------------------------------------------------------------


class Subagent:
    """Encapsulates a single knowledge source: retrieval + scoring + LLM."""

    def __init__(
        self,
        subagent_id: str,
        retriever: Retriever,
        confidence_scorer: ConfidenceScorer,
        llm: LLMInterface,
        k: int = 5,
    ):
        self.subagent_id = subagent_id
        self._retriever = retriever
        self._confidence_scorer = confidence_scorer
        self._llm = llm
        self._k = k

    async def aquery(self, query: str) -> SubagentResponse:
        """Retrieve context, score it, generate an answer, and return results."""
        raw_results = self._retriever.retrieve_raw(query, k=self._k)

        if not raw_results:
            return SubagentResponse(
                subagent_id=self.subagent_id,
                answer="",
                confidence_score=0.0,
            )

        confidence = max(
            self._confidence_scorer.score(query, chunk.text, sim)
            for chunk, sim in raw_results
        )

        context = Retriever.format_context(raw_results)
        answer = await self._llm.complete(context, query)

        sources = [
            SourceMetadata(
                doc_id=chunk.doc_id,
                url_or_path=chunk.url_or_path,
                chunk_index=chunk.chunk_index,
            )
            for chunk, _ in raw_results
        ]

        return SubagentResponse(
            subagent_id=self.subagent_id,
            answer=answer,
            confidence_score=confidence,
            sources=sources,
        )
