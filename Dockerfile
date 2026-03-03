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
RUN useradd --create-home --shell /bin/bash erks
WORKDIR /home/erks/app

# Copy the venv and source from the builder stage
COPY --from=builder /app/.venv /home/erks/app/.venv
COPY --chown=erks:erks src/ ./src/
COPY --chown=erks:erks main.py ./

# Make the virtualenv's binaries the default
ENV PATH="/home/erks/app/.venv/bin:$PATH"

# Default writable paths for logs and data (can be overridden via config.yaml)
RUN mkdir -p /home/erks/logs /home/erks/data/subagents /home/erks/data/subagents/failed \
    && chown -R erks:erks /home/erks/logs /home/erks/data

USER erks

EXPOSE 8000

# ERKS_CONFIG_PATH can point to a mounted config file (see docker run example below).
# If unset the server starts with built-in defaults.
ENV ERKS_CONFIG_PATH=""

# ── Healthcheck ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" \
    || exit 1

# Start uvicorn bound to all interfaces so the container is reachable over LAN
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
