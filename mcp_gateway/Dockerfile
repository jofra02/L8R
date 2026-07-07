# MCP Gateway — generic OpenAPI→MCP server (see docs/architecture/mcp_gateway.md)
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Defaults (overridable via compose environment)
ENV SERVER_PORT=8000 \
    SERVER_TRANSPORT=sse \
    UVICORN_RELOAD=false \
    LOG_LEVEL=info

WORKDIR /app

# Install dependencies from the lockfile (no project package to install)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Application code. The device inventory is volume-mounted, never baked in.
COPY gateway ./gateway
COPY vendors ./vendors
COPY main.py ./

RUN useradd -m appuser
USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE ${SERVER_PORT}

CMD ["python", "main.py"]
