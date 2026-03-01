"""Production wiring: constructs orchestrator from config."""

from __future__ import annotations

import logging
import logging.handlers
import os

from erks.config import Config
from erks.orchestrator.in_memory import InMemoryOrchestrator
from erks.server.mcp_server import create_mcp_server
from erks.subagent.ingestion import DeterministicEmbedder, IngestionPipeline


def setup_logging(config: Config) -> None:
    """Configure rotating file logger."""
    log_path = config.log.path
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=config.log.max_bytes,
        backupCount=config.log.backup_count,
    )
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler, logging.StreamHandler()],
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def create_production_server(config: Config | None = None):
    """Creates and returns a production FastMCP server wired with real orchestrator."""
    if config is None:
        config = Config.default()

    embedder = DeterministicEmbedder()  # Replace with real embedder in production
    pipeline = IngestionPipeline(embedder)
    orchestrator = InMemoryOrchestrator(config, pipeline)
    return create_mcp_server(orchestrator)
