"""Tests for src/config.py – all dataclasses, validation, from_yaml, and default()."""

from __future__ import annotations

import textwrap

import pytest

from src.config import (
    Config,
    LLMConfig,
    LogConfig,
    OrchestratorConfig,
    SecretsConfig,
    StorageConfig,
)


# ---------------------------------------------------------------------------
# OrchestratorConfig validation
# ---------------------------------------------------------------------------


def test_orchestrator_config_defaults():
    cfg = OrchestratorConfig()
    assert cfg.max_subagents == 20
    assert cfg.max_concurrent_ingestions == 2
    assert cfg.default_ingestion_timeout_seconds == 60
    assert cfg.default_embedding_model == "default-embedding-model"
    assert cfg.embedding_batch_size == 64
    assert cfg.query_timeout_ms == 500


def test_orchestrator_config_max_subagents_zero_raises():
    with pytest.raises(ValueError, match="max_subagents must be > 0"):
        OrchestratorConfig(max_subagents=0)


def test_orchestrator_config_max_subagents_negative_raises():
    with pytest.raises(ValueError, match="max_subagents must be > 0"):
        OrchestratorConfig(max_subagents=-5)


def test_orchestrator_config_max_concurrent_ingestions_zero_raises():
    with pytest.raises(ValueError, match="max_concurrent_ingestions must be > 0"):
        OrchestratorConfig(max_concurrent_ingestions=0)


def test_orchestrator_config_ingestion_timeout_zero_raises():
    with pytest.raises(
        ValueError, match="default_ingestion_timeout_seconds must be > 0"
    ):
        OrchestratorConfig(default_ingestion_timeout_seconds=0)


def test_orchestrator_config_embedding_batch_size_zero_raises():
    with pytest.raises(ValueError, match="embedding_batch_size must be > 0"):
        OrchestratorConfig(embedding_batch_size=0)


def test_orchestrator_config_query_timeout_ms_zero_raises():
    with pytest.raises(ValueError, match="query_timeout_ms must be > 0"):
        OrchestratorConfig(query_timeout_ms=0)


def test_orchestrator_config_custom_values():
    cfg = OrchestratorConfig(
        max_subagents=5,
        max_concurrent_ingestions=3,
        default_ingestion_timeout_seconds=30,
        embedding_batch_size=32,
        query_timeout_ms=1000,
    )
    assert cfg.max_subagents == 5
    assert cfg.max_concurrent_ingestions == 3
    assert cfg.default_ingestion_timeout_seconds == 30
    assert cfg.embedding_batch_size == 32
    assert cfg.query_timeout_ms == 1000


# ---------------------------------------------------------------------------
# LogConfig validation
# ---------------------------------------------------------------------------


def test_log_config_defaults():
    cfg = LogConfig()
    assert cfg.path == "/var/log/graph-hopper/orchestrator.log"
    assert cfg.max_bytes == 104857600
    assert cfg.backup_count == 5


def test_log_config_max_bytes_zero_raises():
    with pytest.raises(ValueError, match="max_bytes must be > 0"):
        LogConfig(max_bytes=0)


def test_log_config_max_bytes_negative_raises():
    with pytest.raises(ValueError, match="max_bytes must be > 0"):
        LogConfig(max_bytes=-1)


def test_log_config_backup_count_negative_raises():
    with pytest.raises(ValueError, match="backup_count must be >= 0"):
        LogConfig(backup_count=-1)


def test_log_config_backup_count_zero_allowed():
    cfg = LogConfig(backup_count=0)
    assert cfg.backup_count == 0


def test_log_config_custom_path():
    cfg = LogConfig(path="/tmp/my-app.log", max_bytes=1024, backup_count=2)
    assert cfg.path == "/tmp/my-app.log"
    assert cfg.max_bytes == 1024
    assert cfg.backup_count == 2


# ---------------------------------------------------------------------------
# StorageConfig
# ---------------------------------------------------------------------------


def test_storage_config_defaults():
    cfg = StorageConfig()
    assert cfg.base_path == "/var/lib/graph-hopper/subagents"
    assert cfg.failed_path == "/var/lib/graph-hopper/subagents/failed"


def test_storage_config_custom():
    cfg = StorageConfig(base_path="/data/agents", failed_path="/data/agents/failed")
    assert cfg.base_path == "/data/agents"
    assert cfg.failed_path == "/data/agents/failed"


# ---------------------------------------------------------------------------
# SecretsConfig
# ---------------------------------------------------------------------------


def test_secrets_config_defaults():
    cfg = SecretsConfig()
    assert cfg.store_type == "file"
    assert cfg.path == "/etc/graph-hopper/secrets.yaml"


def test_secrets_config_custom():
    cfg = SecretsConfig(store_type="env", path="/tmp/secrets.yaml")
    assert cfg.store_type == "env"
    assert cfg.path == "/tmp/secrets.yaml"


# ---------------------------------------------------------------------------
# LLMConfig validation
# ---------------------------------------------------------------------------


def test_llm_config_defaults():
    cfg = LLMConfig()
    assert cfg.provider == "openrouter"
    assert cfg.api_key == ""
    assert cfg.subagent_model == "openrouter/openai/gpt-4o-mini"
    assert cfg.orchestrator_model == "openrouter/openai/gpt-4o"
    assert cfg.subagent_timeout_seconds == 15.0


def test_llm_config_timeout_zero_raises():
    with pytest.raises(ValueError, match="subagent_timeout_seconds must be > 0"):
        LLMConfig(subagent_timeout_seconds=0)


def test_llm_config_timeout_negative_raises():
    with pytest.raises(ValueError, match="subagent_timeout_seconds must be > 0"):
        LLMConfig(subagent_timeout_seconds=-1.0)


def test_llm_config_custom():
    cfg = LLMConfig(
        provider="openai",
        api_key="sk-test-key",
        subagent_model="gpt-4o-mini",
        orchestrator_model="gpt-4o",
        subagent_timeout_seconds=30.0,
    )
    assert cfg.provider == "openai"
    assert cfg.api_key == "sk-test-key"
    assert cfg.subagent_timeout_seconds == 30.0


# ---------------------------------------------------------------------------
# Config.default()
# ---------------------------------------------------------------------------


def test_config_default_returns_config():
    cfg = Config.default()
    assert isinstance(cfg, Config)
    assert isinstance(cfg.orchestrator, OrchestratorConfig)
    assert isinstance(cfg.log, LogConfig)
    assert isinstance(cfg.storage, StorageConfig)
    assert isinstance(cfg.secrets, SecretsConfig)
    assert isinstance(cfg.llm, LLMConfig)


def test_config_default_subcomponents_have_correct_defaults():
    cfg = Config.default()
    assert cfg.orchestrator.max_subagents == 20
    assert cfg.log.backup_count == 5
    assert cfg.llm.provider == "openrouter"


# ---------------------------------------------------------------------------
# Config.from_yaml()
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path, content: str) -> str:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content))
    return str(p)


def test_from_yaml_empty_file_uses_defaults(tmp_path):
    path = _write_yaml(tmp_path, "")
    cfg = Config.from_yaml(path)
    assert cfg.orchestrator.max_subagents == 20
    assert cfg.log.backup_count == 5
    assert cfg.llm.provider == "openrouter"


def test_from_yaml_partial_override(tmp_path):
    path = _write_yaml(
        tmp_path,
        """
        orchestrator:
          max_subagents: 5
          query_timeout_ms: 1000
        log:
          path: /tmp/test.log
        """,
    )
    cfg = Config.from_yaml(path)
    assert cfg.orchestrator.max_subagents == 5
    assert cfg.orchestrator.query_timeout_ms == 1000
    assert cfg.log.path == "/tmp/test.log"
    # Unspecified values keep defaults
    assert cfg.orchestrator.max_concurrent_ingestions == 2
    assert cfg.llm.provider == "openrouter"


def test_from_yaml_full_override(tmp_path):
    path = _write_yaml(
        tmp_path,
        """
        orchestrator:
          max_subagents: 10
          max_concurrent_ingestions: 4
          default_ingestion_timeout_seconds: 120
          default_embedding_model: custom-embed
          embedding_batch_size: 128
          query_timeout_ms: 2000
        log:
          path: /tmp/erks.log
          max_bytes: 52428800
          backup_count: 3
        storage:
          base_path: /data/agents
          failed_path: /data/agents/failed
        secrets:
          store_type: env
          path: /tmp/secrets.yaml
        llm:
          provider: openai
          api_key: sk-test
          subagent_model: gpt-4o-mini
          orchestrator_model: gpt-4o
          subagent_timeout_seconds: 20.0
        """,
    )
    cfg = Config.from_yaml(path)
    assert cfg.orchestrator.max_subagents == 10
    assert cfg.orchestrator.embedding_batch_size == 128
    assert cfg.log.path == "/tmp/erks.log"
    assert cfg.log.max_bytes == 52428800
    assert cfg.storage.base_path == "/data/agents"
    assert cfg.secrets.store_type == "env"
    assert cfg.llm.provider == "openai"
    assert cfg.llm.api_key == "sk-test"
    assert cfg.llm.subagent_timeout_seconds == 20.0


def test_from_yaml_invalid_value_raises(tmp_path):
    path = _write_yaml(
        tmp_path,
        """
        orchestrator:
          max_subagents: 0
        """,
    )
    with pytest.raises(ValueError, match="max_subagents must be > 0"):
        Config.from_yaml(path)


def test_from_yaml_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        Config.from_yaml("/nonexistent/path/config.yaml")


def test_from_yaml_llm_section_only(tmp_path):
    path = _write_yaml(
        tmp_path,
        """
        llm:
          api_key: my-key
          subagent_timeout_seconds: 10.0
        """,
    )
    cfg = Config.from_yaml(path)
    assert cfg.llm.api_key == "my-key"
    assert cfg.llm.subagent_timeout_seconds == 10.0
    assert cfg.orchestrator.max_subagents == 20  # default
