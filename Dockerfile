# ─── Build stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy dependency manifests first to maximise Docker layer cache reuse
COPY pyproject.toml uv.lock ./

# Install all project dependencies into a virtual environment
RUN uv sync --frozen --no-dev

# ─── Runtime stage ───────────────────────────────────────────────────────────
FROM python:3.11-slim

# Non-root user for security
RUN useradd --create-home --shell /bin/bash graph-hopper
WORKDIR /home/graph-hopper/app

# Copy the venv and source from the builder stage
COPY --from=builder /app/.venv /home/graph-hopper/app/.venv
COPY --chown=graph-hopper:graph-hopper src/ ./src/
COPY --chown=graph-hopper:graph-hopper main.py ./

# Make the virtualenv's binaries the default
ENV PATH="/home/graph-hopper/app/.venv/bin:$PATH"

# Default writable paths for logs and data (can be overridden via config.yaml)
RUN mkdir -p /home/graph-hopper/logs /home/graph-hopper/data/subagents /home/graph-hopper/data/subagents/failed \
    && chown -R graph-hopper:graph-hopper /home/graph-hopper/logs /home/graph-hopper/data

USER graph-hopper

EXPOSE 8000

# GRAPH_HOPPER_CONFIG_PATH can point to a mounted config file (see docker run example below).
# If unset the server starts with built-in defaults.
ENV GRAPH_HOPPER_CONFIG_PATH=""

# ── Healthcheck ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" \
    || exit 1

# Start uvicorn bound to all interfaces so the container is reachable over LAN
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
