"""Production wiring: constructs orchestrator from config."""

from __future__ import annotations

import logging
import logging.handlers
import os

from mcp.server.transport_security import TransportSecuritySettings

from src.config import Config
from src.orchestrator.in_memory import InMemoryOrchestrator
from src.server.mcp_server import create_mcp_server
from src.subagent.ingestion import FastEmbedder, IngestionPipeline


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

    embedder = FastEmbedder(
        model_name=config.orchestrator.default_embedding_model,
        batch_size=config.orchestrator.embedding_batch_size,
    )
    pipeline = IngestionPipeline(embedder)
    orchestrator = InMemoryOrchestrator(config, pipeline)

    allowed_hosts = config.server.allowed_hosts
    transport_security = (
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
        )
        if allowed_hosts
        else TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )

    return create_mcp_server(orchestrator, transport_security=transport_security)
