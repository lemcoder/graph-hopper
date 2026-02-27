"""Orchestrator protocol definition."""
from typing import Protocol, runtime_checkable

from erks.models import SourceConfig, AddSourceResult, QueryResult, ListSourcesResult


@runtime_checkable
class OrchestratorInterface(Protocol):
    async def add_source(self, config: SourceConfig) -> AddSourceResult: ...
    async def query(self, query: str) -> QueryResult: ...
    def list_sources(self) -> ListSourcesResult: ...
