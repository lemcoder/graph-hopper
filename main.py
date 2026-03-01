"""Entrypoint for the ERKS MCP server.

The server is configured via a YAML file whose path is read from the
``ERKS_CONFIG_PATH`` environment variable.  When the variable is not set the
application falls back to built-in defaults (``Config.default()``).

Run with uvicorn::

    uvicorn main:app --host 0.0.0.0 --port 8000

Or use the ``erks-server`` shortcut defined in ``pyproject.toml``::

    uv run erks-server
"""

from __future__ import annotations

import os

from erks.config import Config
from erks.server.wiring import create_production_server, setup_logging

_config_path = os.environ.get("ERKS_CONFIG_PATH")
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

    host = os.environ.get("ERKS_HOST", "0.0.0.0")
    port = int(os.environ.get("ERKS_PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
