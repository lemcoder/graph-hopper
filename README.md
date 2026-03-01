# ERKS – Extensible Retrieval Knowledge System

ERKS is a **Model Context Protocol (MCP) server** that turns arbitrary document
sources (Git repositories, HTTP pages, etc.) into queryable knowledge bases.
It manages a pool of *subagents* – each responsible for one source – and
dispatches queries to all of them in parallel, returning the most confident
answer.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Quick Start](#quick-start)
3. [Configuration](#configuration)
4. [Deployment Options](#deployment-options)
   - [Bare Metal (Raspberry Pi / Localhost)](#1-bare-metal-raspberry-pi--localhost)
   - [Docker](#2-docker)
5. [MCP Tools Reference](#mcp-tools-reference)
6. [Development](#development)
7. [CI/CD](#cicd)

---

## Architecture Overview

```
MCP Client (e.g. Claude Desktop, Cursor)
        │  MCP protocol (Streamable HTTP / SSE)
        ▼
┌──────────────────────────────┐
│      FastMCP Server          │
│  add_source / query /        │
│  list_sources tools          │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│    InMemoryOrchestrator      │
│  • subagent registry         │
│  • concurrency semaphore     │
│  • parallel query dispatch   │
└──────────┬───────────────────┘
           │  one per source
           ▼
┌──────────────────────────────┐
│    Subagent                  │
│  IngestionPipeline →         │
│  VectorStore (FAISS) →       │
│  Retriever →                 │
│  ConfidenceScorer →          │
│  LLM (OpenRouter / mock)     │
└──────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Clone and install

```bash
git clone https://github.com/lemcoder/graph-hopper.git
cd graph-hopper
uv sync
```

### Run with defaults (no config file needed)

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The server will start and be accessible at `http://localhost:8000`.

---

## Configuration

ERKS reads its configuration from a YAML file.  Point the server at your file
by setting the `ERKS_CONFIG_PATH` environment variable:

```bash
export ERKS_CONFIG_PATH=/path/to/config.yaml
uvicorn main:app --host 0.0.0.0 --port 8000
```

An annotated example (`config.yaml`) is included in the root of the repository.

### Key configuration sections

| Section | Purpose |
|---------|---------|
| `orchestrator` | Subagent limits, concurrency, timeouts, embedding |
| `log` | Log file path, rotation size, backup count |
| `storage` | Paths for subagent data and failed-task records |
| `secrets` | Secret store type and path |
| `llm` | LLM provider, API key, model names, timeout |

> **Raspberry Pi / non-root users:** The default paths under `/var/log/` and
> `/var/lib/` require root permissions.  Override them in your config file to
> user-writable locations, for example:
>
> ```yaml
> log:
>   path: logs/orchestrator.log
> storage:
>   base_path: data/subagents
>   failed_path: data/subagents/failed
> ```

### Providing the API key

It is recommended to set your LLM API key through an environment variable
rather than storing it in a file:

```bash
export OPENROUTER_API_KEY=your-key-here
```

Or include it directly in `config.yaml` under `llm.api_key` (keep that file
out of version control).

---

## Deployment Options

### 1. Bare Metal (Raspberry Pi / Localhost)

#### Install

```bash
git clone https://github.com/lemcoder/graph-hopper.git
cd graph-hopper
uv sync
```

#### Configure

Copy and edit the example config:

```bash
cp config.yaml my-config.yaml
# Edit my-config.yaml – at minimum, set log.path and storage.base_path to
# user-writable directories and set llm.api_key (or use an env var).
nano my-config.yaml
```

#### Run

```bash
export ERKS_CONFIG_PATH=my-config.yaml
export OPENROUTER_API_KEY=your-key-here
uvicorn main:app --host 0.0.0.0 --port 8000
```

The `--host 0.0.0.0` flag makes the server reachable from other devices on
the same LAN (e.g. your laptop can connect to the Pi at
`http://raspberrypi.local:8000`).

#### Run as a systemd service (optional)

```ini
# /etc/systemd/system/erks.service
[Unit]
Description=ERKS MCP Server
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/graph-hopper
Environment="ERKS_CONFIG_PATH=/home/pi/graph-hopper/my-config.yaml"
Environment="OPENROUTER_API_KEY=your-key-here"
ExecStart=/home/pi/graph-hopper/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable erks
sudo systemctl start erks
```

---

### 2. Docker

Docker provides an isolated, reproducible environment and is the easiest way
to run ERKS on any machine without installing Python or uv.

#### Build

```bash
docker build -t erks:latest .
```

> **Raspberry Pi (ARM64):** Build for the Pi's architecture with:
> ```bash
> docker buildx build --platform linux/arm64 -t erks:latest .
> ```

#### Run

```bash
docker run -d \
  --name erks \
  -p 8000:8000 \
  -v "$(pwd)/my-config.yaml:/home/erks/app/config.yaml:ro" \
  -v "$(pwd)/data:/home/erks/data" \
  -v "$(pwd)/logs:/home/erks/logs" \
  -e ERKS_CONFIG_PATH=/home/erks/app/config.yaml \
  -e OPENROUTER_API_KEY=your-key-here \
  erks:latest
```

| Flag | Purpose |
|------|---------|
| `-p 8000:8000` | Expose port 8000 to the host / LAN |
| `-v ./my-config.yaml:…` | Mount your config file (read-only) |
| `-v ./data:…` | Persist subagent indexes across container restarts |
| `-v ./logs:…` | Persist log files on the host |
| `-e ERKS_CONFIG_PATH=…` | Tell the server where to find the config |
| `-e OPENROUTER_API_KEY=…` | Pass the API key securely |

#### Verify

```bash
curl http://localhost:8000/
```

#### Stop / Remove

```bash
docker stop erks && docker rm erks
```

---

## MCP Tools Reference

### `add_source`

Register and ingest a new knowledge source.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `type` | string | ✅ | `"git"` or `"http"` |
| `location` | string | ✅ | URL of the repository or document |
| `name` | string | | Human-readable label |
| `source_id` | string | | Stable ID; re-ingests if already registered |
| `auth_secret_id` | string | | Secret store key for auth credentials |
| `build_graph` | bool | | Build knowledge graph (default: `false`) |
| `metadata` | object | | Arbitrary key/value metadata |

**Returns:** `{ "subagent_id": "...", "status": "ready" | "failed" }`

### `query`

Send a natural-language question to all ready subagents.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | ✅ | The question to answer |

**Returns:**
```json
{
  "answer": "...",
  "confidence": 0.85,
  "subagent_id": "sa_abc123",
  "sources": [...],
  "meta": {
    "latency_ms": 42,
    "queried_subagents_count": 3,
    "success_count": 2,
    "errors": []
  }
}
```

### `list_sources`

List all registered subagents and their current status.

**Returns:**
```json
{
  "sources": [
    {
      "subagent_id": "sa_abc123",
      "name": "my-repo",
      "type": "git",
      "location": "https://github.com/...",
      "status": "ready",
      "created_at": "2024-01-01T00:00:00Z",
      "last_updated": "2024-01-01T00:01:00Z"
    }
  ],
  "total": 1,
  "max_allowed": 20
}
```

---

## Development

### Run tests

```bash
uv run pytest
```

Tests automatically enforce **≥ 90% code coverage** (`--cov-fail-under=90`).

### Run a single test file

```bash
uv run pytest tests/unit/test_orchestrator.py -v
```

### Lint

```bash
uv run ruff check .
uv run ruff format --check .
```

### Auto-fix lint issues

```bash
uv run ruff check --fix .
uv run ruff format .
```

### Project layout

```
graph-hopper/
├── erks/                    # Application package
│   ├── config.py            # Configuration dataclasses + YAML loader
│   ├── models.py            # Shared Pydantic models and exceptions
│   ├── orchestrator/        # InMemoryOrchestrator (core dispatch logic)
│   ├── server/              # FastMCP server factory + production wiring
│   └── subagent/            # Ingestion, embedding, retrieval, scoring
├── tests/
│   ├── fixtures/            # Golden fixture documents (ground-truth test data)
│   ├── unit/                # Unit tests (mocked, in-memory, deterministic)
│   └── integration/         # End-to-end tests against the full MCP stack
├── spec/                    # Detailed functional specifications
├── config.yaml              # Annotated example configuration file
├── Dockerfile               # Multi-stage Docker image
├── main.py                  # Uvicorn entrypoint (reads ERKS_CONFIG_PATH)
└── pyproject.toml           # Python project metadata and dependencies
```

---

## CI/CD

Two GitHub Actions workflows run on every push and pull request:

| Workflow | File | Purpose |
|----------|------|---------|
| **Tests** | `.github/workflows/tests.yml` | Lint (ruff) + pytest with ≥ 90% coverage gate |
| **Docker Build** | `.github/workflows/docker.yml` | Verify the Docker image builds successfully |

Merges to `main` are only allowed when both workflows pass.
