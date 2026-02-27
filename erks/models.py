"""Shared Pydantic models and exceptions for ERKS."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class SourceType(str, Enum):
    GIT = "git"
    HTTP = "http"


class SubagentStatus(str, Enum):
    PENDING = "pending"
    INGESTING = "ingesting"
    READY = "ready"
    FAILED = "failed"


class SourceConfig(BaseModel):
    type: SourceType
    location: str
    name: Optional[str] = None
    source_id: Optional[str] = None
    auth_secret_id: Optional[str] = None
    build_graph: bool = False
    metadata: Optional[dict] = None


class SubagentRecord(BaseModel):
    subagent_id: str
    name: Optional[str] = None
    type: SourceType
    location: str
    status: SubagentStatus
    created_at: datetime
    last_updated: datetime
    last_error: Optional[str] = None
    metadata: Optional[dict] = None


class AddSourceResult(BaseModel):
    subagent_id: Optional[str] = None
    status: SubagentStatus
    last_error: Optional[str] = None


class CapExceededError(Exception):
    code: str = "MAX_SUBAGENTS_EXCEEDED"

    def __init__(self, current_count: int, max_subagents: int):
        self.current_count = current_count
        self.max_subagents = max_subagents
        self.message = (
            f"cannot add source: maximum number of subagents ({max_subagents}) reached"
        )
        super().__init__(self.message)


class ValidationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class QueryResult(BaseModel):
    answer: str
    confidence: float
    subagent_id: str
    alternatives: Optional[list] = None
    sources: list = []
    meta: dict = {}


class ListSourcesResult(BaseModel):
    sources: list[SubagentRecord]
    total: int
    max_allowed: int
