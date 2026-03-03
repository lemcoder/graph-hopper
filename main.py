"""Entrypoint for the Graph Hopper MCP server.

The server is configured via a YAML file whose path is read from the
``GRAPH_HOPPER_CONFIG_PATH`` environment variable.  When the variable is not set the
application falls back to built-in defaults (``Config.default()``).

Run with uvicorn::

    uvicorn main:app --host 0.0.0.0 --port 8000

Or use the ``graph-hopper-server`` shortcut defined in ``pyproject.toml``::

    uv run graph-hopper-server
"""

from __future__ import annotations

import os

from src.config import Config
from src.server.wiring import create_production_server, setup_logging

_config_path = os.environ.get("GRAPH_HOPPER_CONFIG_PATH")
if _config_path:
    _config = Config.from_yaml(_config_path)
else:
    _config = Config.default()

setup_logging(_config)

# ``app`` is the FastMCP ASGI application consumed by uvicorn.
app = create_production_server(_config)


def main() -> None:
    """CLI entrypoint – starts uvicorn programmatically."""
    import uvicorn  # type: ignore

    host = os.environ.get("GRAPH_HOPPER_HOST", "0.0.0.0")
    port = int(os.environ.get("GRAPH_HOPPER_PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
