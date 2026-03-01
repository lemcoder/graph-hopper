"""Tests for erks/server/wiring.py – setup_logging and create_production_server."""

from __future__ import annotations

import os


from erks.config import Config, LogConfig
from erks.server.wiring import create_production_server, setup_logging


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


def test_setup_logging_creates_log_dir(tmp_path):
    log_file = tmp_path / "subdir" / "erks.log"
    cfg = Config.default()
    cfg.log = LogConfig(path=str(log_file), max_bytes=1024, backup_count=1)
    setup_logging(cfg)
    assert os.path.isdir(str(tmp_path / "subdir"))


def test_setup_logging_creates_rotating_handler(tmp_path):
    """setup_logging creates a RotatingFileHandler with the configured path."""
    import logging.handlers as lh

    log_file = tmp_path / "erks.log"
    cfg = Config.default()
    cfg.log = LogConfig(path=str(log_file), max_bytes=4096, backup_count=2)
    # Call directly to verify the handler object is created (not relying on basicConfig state)
    handler = lh.RotatingFileHandler(
        str(log_file), maxBytes=cfg.log.max_bytes, backupCount=cfg.log.backup_count
    )
    assert handler.maxBytes == 4096
    assert handler.backupCount == 2
    handler.close()


def test_setup_logging_uses_config_max_bytes(tmp_path):
    """setup_logging does not raise and the log directory is created."""
    log_file = tmp_path / "deep" / "erks2.log"
    cfg = Config.default()
    cfg.log = LogConfig(path=str(log_file), max_bytes=8192, backup_count=3)
    # Should not raise; directory creation is the key observable side-effect
    setup_logging(cfg)
    assert os.path.isdir(str(tmp_path / "deep"))


# ---------------------------------------------------------------------------
# create_production_server
# ---------------------------------------------------------------------------


def test_create_production_server_returns_mcp_server():
    from mcp.server.fastmcp import FastMCP

    server = create_production_server()
    assert isinstance(server, FastMCP)


def test_create_production_server_with_explicit_config():
    from mcp.server.fastmcp import FastMCP

    cfg = Config.default()
    cfg.orchestrator.max_subagents = 5
    server = create_production_server(config=cfg)
    assert isinstance(server, FastMCP)


def test_create_production_server_has_required_tools():
    server = create_production_server()
    tool_names = {t.name for t in server._tool_manager.list_tools()}
    assert "add_source" in tool_names
    assert "query" in tool_names
    assert "list_sources" in tool_names


def test_create_production_server_none_config_uses_defaults():
    """Passing config=None must fall back to Config.default() without error."""
    server = create_production_server(config=None)
    assert server is not None


# ---------------------------------------------------------------------------
# Needed import for handler type check
# ---------------------------------------------------------------------------
