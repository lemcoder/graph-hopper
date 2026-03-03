"""In-memory orchestrator implementation."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from src.config import Config
from src.models import (
    AddSourceResult,
    CapExceededError,
    ListSourcesResult,
    QueryResult,
    SourceConfig,
    SourceType,
    SubagentRecord,
    SubagentStatus,
    ValidationError as ErksValidationError,
)
from src.subagent.confidence import ConfidenceScorer
from src.subagent.ingestion import DeterministicEmbedder, IngestionPipeline
from src.subagent.retriever import Retriever
from src.subagent.subagent import MockLLM, Subagent, SubagentResponse
from src.subagent.vector_store import VectorStore

logger = logging.getLogger(__name__)

ALLOWED_SOURCE_TYPES = {SourceType.GIT, SourceType.HTTP}


class InMemoryOrchestrator:
    """
    In-memory orchestrator implementation. Thread-safe via asyncio.
    Suitable for tests and lightweight deployments.
    """

    def __init__(
        self,
        config: Config,
        pipeline: Optional[IngestionPipeline] = None,
        llm=None,
    ):
        self._config = config
        self._registry: dict[str, SubagentRecord] = {}
        self._subagent_instances: dict[str, Subagent] = {}
        self._pipeline = pipeline or IngestionPipeline(DeterministicEmbedder())
        self._llm = llm or MockLLM()
        self._semaphore = asyncio.Semaphore(
            config.orchestrator.max_concurrent_ingestions
        )

    def _validate_source_type(self, source_type: SourceType) -> None:
        if source_type not in ALLOWED_SOURCE_TYPES:
            raise ErksValidationError(
                f"Unsupported source type '{source_type}'. "
                f"Allowed types: {', '.join(t.value for t in ALLOWED_SOURCE_TYPES)}"
            )

    def _check_cap(self, source_id: Optional[str]) -> None:
        current_count = len(self._registry)
        is_update = bool(source_id and source_id in self._registry)
        if not is_update and current_count >= self._config.orchestrator.max_subagents:
            raise CapExceededError(
                current_count=current_count,
                max_subagents=self._config.orchestrator.max_subagents,
            )

    async def add_source(self, config: SourceConfig) -> AddSourceResult:
        logger.info(
            "add_source received: type=%s location=%s source_id=%s",
            config.type,
            config.location,
            config.source_id,
        )

        self._validate_source_type(config.type)
        self._check_cap(config.source_id)

        is_update = bool(config.source_id and config.source_id in self._registry)
        subagent_id = config.source_id or f"sa_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)

        if is_update:
            record = self._registry[subagent_id]
            record.status = SubagentStatus.INGESTING
            record.last_updated = now
        else:
            record = SubagentRecord(
                subagent_id=subagent_id,
                name=config.name,
                type=config.type,
                location=config.location,
                status=SubagentStatus.INGESTING,
                created_at=now,
                last_updated=now,
                metadata=config.metadata,
            )
            self._registry[subagent_id] = record

        timeout = self._config.orchestrator.default_ingestion_timeout_seconds
        try:
            async with self._semaphore:
                async with asyncio.timeout(timeout):
                    result = await self._pipeline.ingest(config)

            # Build the per-subagent vector store and wire up the subagent
            dims = len(result.embeddings[0]) if result.embeddings else 384
            vs = VectorStore(dimensions=dims)
            vs.build(result.embeddings, result.chunks)

            retriever = Retriever(self._pipeline.embedder, vs)
            subagent = Subagent(
                subagent_id=subagent_id,
                retriever=retriever,
                confidence_scorer=ConfidenceScorer(),
                llm=self._llm,
            )
            self._subagent_instances[subagent_id] = subagent

            record.status = SubagentStatus.READY
            record.last_updated = datetime.now(timezone.utc)
            record.last_error = None
            logger.info(
                "add_source succeeded: subagent_id=%s chunks=%d",
                subagent_id,
                len(result.chunks),
            )
            return AddSourceResult(subagent_id=subagent_id, status=SubagentStatus.READY)

        except asyncio.TimeoutError:
            record.status = SubagentStatus.FAILED
            record.last_error = f"Ingestion timed out after {timeout}s"
            record.last_updated = datetime.now(timezone.utc)
            logger.error("add_source timed out: subagent_id=%s", subagent_id)
            return AddSourceResult(
                subagent_id=subagent_id,
                status=SubagentStatus.FAILED,
                last_error=record.last_error,
            )
        except Exception as exc:
            record.status = SubagentStatus.FAILED
            record.last_error = str(exc)
            record.last_updated = datetime.now(timezone.utc)
            logger.error("add_source failed: subagent_id=%s error=%s", subagent_id, exc)
            return AddSourceResult(
                subagent_id=subagent_id,
                status=SubagentStatus.FAILED,
                last_error=record.last_error,
            )

    async def query(self, query: str) -> QueryResult:
        ready_agents = [
            r for r in self._registry.values() if r.status == SubagentStatus.READY
        ]

        if not ready_agents:
            return QueryResult(
                answer="No ready subagents available to answer the query.",
                confidence=0.0,
                subagent_id="",
                meta={
                    "latency_ms": 0,
                    "queried_subagents_count": 0,
                    "success_count": 0,
                    "errors": [],
                },
            )

        start = time.monotonic()
        timeout_s = self._config.orchestrator.query_timeout_ms / 1000.0

        errors: list[dict] = []

        async def _query_one(record: SubagentRecord) -> Optional[SubagentResponse]:
            sa = self._subagent_instances.get(record.subagent_id)
            if sa is None:
                return None
            try:
                return await asyncio.wait_for(sa.aquery(query), timeout=timeout_s)
            except Exception as exc:
                logger.warning(
                    "Subagent %s failed or timed out: %s", record.subagent_id, exc
                )
                errors.append({"subagent_id": record.subagent_id, "error": str(exc)})
                return None

        responses = await asyncio.gather(*[_query_one(a) for a in ready_agents])
        valid: list[SubagentResponse] = [r for r in responses if r is not None]

        latency_ms = int((time.monotonic() - start) * 1000)

        if not valid:
            return QueryResult(
                answer="No subagents responded within the query timeout.",
                confidence=0.0,
                subagent_id="",
                meta={
                    "latency_ms": latency_ms,
                    "queried_subagents_count": len(ready_agents),
                    "success_count": 0,
                    "errors": errors,
                },
            )

        def _sort_key(r: SubagentResponse):
            rec = self._registry.get(r.subagent_id)
            created = (
                rec.created_at if rec else datetime.min.replace(tzinfo=timezone.utc)
            )
            return (-r.confidence_score, created, r.subagent_id)

        valid.sort(key=_sort_key)
        best = valid[0]

        alternatives = [
            {
                "answer": r.answer,
                "confidence": r.confidence_score,
                "subagent_id": r.subagent_id,
            }
            for r in valid[1:]
            if r.confidence_score == best.confidence_score
        ]

        return QueryResult(
            answer=best.answer,
            confidence=best.confidence_score,
            subagent_id=best.subagent_id,
            alternatives=alternatives if alternatives else None,
            sources=[
                {
                    "doc_id": s.doc_id,
                    "url_or_path": s.url_or_path,
                    "chunk_index": s.chunk_index,
                }
                for s in best.sources
            ],
            meta={
                "latency_ms": latency_ms,
                "queried_subagents_count": len(ready_agents),
                "success_count": len(valid),
                "errors": errors,
            },
        )

    def list_sources(self) -> ListSourcesResult:
        records = sorted(
            self._registry.values(),
            key=lambda r: (-r.last_updated.timestamp(), r.created_at, r.subagent_id),
        )
        return ListSourcesResult(
            sources=list(records),
            total=len(records),
            max_allowed=self._config.orchestrator.max_subagents,
        )
