"""Configuration dataclasses for graph-hopper."""

from __future__ import annotations

import dataclasses
from typing import Optional
import yaml


@dataclasses.dataclass
class OrchestratorConfig:
    max_subagents: int = 20
    max_concurrent_ingestions: int = 2
    default_ingestion_timeout_seconds: int = 60
    default_embedding_model: str = "default-embedding-model"
    embedding_batch_size: int = 64
    query_timeout_ms: int = 500

    def __post_init__(self):
        if self.max_subagents <= 0:
            raise ValueError("max_subagents must be > 0")
        if self.max_concurrent_ingestions <= 0:
            raise ValueError("max_concurrent_ingestions must be > 0")
        if self.default_ingestion_timeout_seconds <= 0:
            raise ValueError("default_ingestion_timeout_seconds must be > 0")
        if self.embedding_batch_size <= 0:
            raise ValueError("embedding_batch_size must be > 0")
        if self.query_timeout_ms <= 0:
            raise ValueError("query_timeout_ms must be > 0")


@dataclasses.dataclass
class LogConfig:
    path: str = "/var/log/graph-hopper/orchestrator.log"
    max_bytes: int = 104857600  # 100 MB
    backup_count: int = 5

    def __post_init__(self):
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be > 0")
        if self.backup_count < 0:
            raise ValueError("backup_count must be >= 0")


@dataclasses.dataclass
class StorageConfig:
    base_path: str = "/var/lib/graph-hopper/subagents"
    failed_path: str = "/var/lib/graph-hopper/subagents/failed"


@dataclasses.dataclass
class SecretsConfig:
    store_type: str = "file"
    path: str = "/etc/graph-hopper/secrets.yaml"


@dataclasses.dataclass
class LLMConfig:
    provider: str = "openrouter"
    api_key: str = ""
    subagent_model: str = "openrouter/openai/gpt-4o-mini"
    orchestrator_model: str = "openrouter/openai/gpt-4o"
    subagent_timeout_seconds: float = 15.0

    def __post_init__(self):
        if self.subagent_timeout_seconds <= 0:
            raise ValueError("subagent_timeout_seconds must be > 0")


@dataclasses.dataclass
class Config:
    orchestrator: OrchestratorConfig = dataclasses.field(
        default_factory=OrchestratorConfig
    )
    log: LogConfig = dataclasses.field(default_factory=LogConfig)
    storage: StorageConfig = dataclasses.field(default_factory=StorageConfig)
    secrets: SecretsConfig = dataclasses.field(default_factory=SecretsConfig)
    llm: LLMConfig = dataclasses.field(default_factory=LLMConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}

        orchestrator = OrchestratorConfig(**data.get("orchestrator", {}))
        log = LogConfig(**data.get("log", {}))
        storage = StorageConfig(**data.get("storage", {}))
        secrets = SecretsConfig(**data.get("secrets", {}))
        llm = LLMConfig(**data.get("llm", {}))
        return cls(
            orchestrator=orchestrator,
            log=log,
            storage=storage,
            secrets=secrets,
            llm=llm,
        )

    @classmethod
    def default(cls) -> "Config":
        return cls()
