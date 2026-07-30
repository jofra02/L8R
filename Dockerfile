# ── Stage 1: Builder ──
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install project
COPY . .
RUN uv sync --frozen --no-dev

# ── Stage 2: Runtime ──
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --create-home appuser

WORKDIR /app

# Copy virtual env and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app

# Strip CR so a CRLF checkout (Windows) never breaks the entrypoint
RUN sed -i 's/\r$//' scripts/entrypoint.sh

# Ensure venv binaries are on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Pre-create volume mount-points so Docker seeds named volumes with correct ownership
# (logs/ is dockerignored — created here writable so log rotation works)
RUN mkdir -p /app/data/evidence /app/logs

RUN chown -R appuser:appuser /app
USER appuser

# Deploy provenance: scripts/deploy/redeploy.sh bakes the deployed git SHA and
# asserts it against the running container after `up`
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision=$GIT_SHA

EXPOSE 8000

ENTRYPOINT ["bash", "scripts/entrypoint.sh"]
