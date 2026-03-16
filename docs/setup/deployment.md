# Deployment Guide

> Docker, production, and scaling considerations.

## Overview

The support AI agent consists of three runtime components:
1. **FastAPI server** - Webhook ingestion + REST API
2. **PostgreSQL** - Relational state, audit logs, checkpoints
3. **Qdrant** - Vector store for KB, evidence, tool knowledge, CBR

Plus external MCP servers that provide read-only tool access.

## Docker Compose (Development)

A minimal `docker-compose.yml` for local development:

```yaml
version: "3.9"
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: change_me
      POSTGRES_DB: support_agent_db
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage

volumes:
  pgdata:
  qdrant_data:
```

## Production Considerations

### Database

- Use managed PostgreSQL (e.g., AWS RDS, Azure Database, Cloud SQL)
- Enable SSL connections (`DB_HOST` with SSL params)
- Run `uv run alembic upgrade head` as part of deployment pipeline
- Regular backups — audit logs and case state are business-critical

### Qdrant

- Use Qdrant Cloud or a dedicated instance with API key auth
- Set `QDRANT_API_KEY` for authenticated access
- Collections are auto-created by `init_qdrant` with proper indexes
- Back up snapshots for `resolved_tickets` and `tool_knowledge` collections

### API Server

- Run behind a reverse proxy (nginx, Caddy, or cloud LB)
- Use `gunicorn` with `uvicorn` workers for production:
  ```bash
  gunicorn src.ingestion.api:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
  ```
- Set `APP_ENV=production` and `LOG_LEVEL=WARNING`
- Ensure `X-Customer-ID` header is validated/injected by your API gateway

### MCP Servers

- Deploy MCP servers close to the target infrastructure (low latency)
- Use SSE transport for remote servers, stdio for local
- Set appropriate `MCP_SERVER_TIMEOUT` for your network conditions

### Observability

- Deploy Langfuse (self-hosted or cloud) for trace visibility
- Set `LANGFUSE_ENABLED=true` with appropriate keys
- Adjust `LANGFUSE_SAMPLE_RATE` in high-volume environments (e.g., `0.1` for 10%)

### Security

- Never expose the API server directly to the internet without authentication
- All tool execution is read-only; write actions require HITL approval via LangGraph interrupt
- Tenant isolation is enforced at the query level — every DB and Qdrant query filters by `customer_id`
- Rotate `OPENAI_API_KEY` and `LANGFUSE_SECRET_KEY` regularly

## Scaling Notes

- The pipeline is CPU-bound on LLM calls (external API). Horizontal scaling of the API server works well.
- Each pipeline execution is independent per ticket — no shared in-memory state between requests.
- Qdrant and PostgreSQL can be scaled independently based on load patterns.
- Background task execution (via FastAPI `BackgroundTasks`) is single-process. For high throughput, consider Celery or a task queue.

## See Also

- [Quickstart](quickstart.md) - Local development setup
- [Configuration Reference](configuration.md) - All env vars
- [Observability](../architecture/observability.md) - Langfuse integration details
