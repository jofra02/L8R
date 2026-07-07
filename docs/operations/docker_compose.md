# Docker Compose Operations

> Stack lifecycle, observability profile, scaling, and port map.

## Services

| Service | Image/Build | Port (host default) | Notes |
|---|---|---|---|
| `postgres` | postgres:16-alpine | `POSTGRES_PORT` 5432 | volume `pgdata` |
| `qdrant` | qdrant/qdrant:v1.14.0 | `QDRANT_PORT` 6333 / `QDRANT_GRPC_PORT` 6334 | volume `qdrant_data` |
| `mcp-gateway` | build `./mcp_gateway` | `MCP_GATEWAY_PORT` 8001 → 8000 | needs `INVENTORY_MASTER_KEY`, `ACTIVE_CUSTOMER_ID`; mounts `./mcp_gateway/inventory:ro` |
| `app` | build `.` | `APP_PORT` 8000 | entrypoint runs migrations + init_qdrant, then uvicorn/gunicorn |
| `frontend` | build `./frontend` | `FRONTEND_PORT` 3001 → 80 | nginx |
| `langfuse` | langfuse/langfuse:2 | `LANGFUSE_PORT` 3000 | **profile `observability`** only |

## Base operations

```bash
docker compose up -d                  # full base stack
docker compose up -d mcp-gateway      # one service
docker compose ps                     # health overview
docker compose logs -f app            # follow logs
docker compose build app && docker compose up -d app   # rebuild + replace
docker compose down                   # stop (volumes preserved)
```

## Observability profile (Langfuse)

One-time bootstrap (Langfuse needs its own database + secrets):

```bash
docker compose exec postgres createdb -U ${DB_USER:-postgres} langfuse
# in .env: LANGFUSE_NEXTAUTH_SECRET=$(openssl rand -base64 32), LANGFUSE_SALT=$(openssl rand -base64 32)
docker compose --profile observability -f docker-compose.yml -f docker-compose.observability.yml up -d
```

Then create the Langfuse project in its UI (`:3000`) and put the public/secret keys + `LANGFUSE_ENABLED=true` in `.env`. Full walkthrough: [deployment.md](../setup/deployment.md).

## Scaling

```bash
docker compose up -d --scale app=3    # multiple app workers (stateless API; background runs are per-process)
```

Set `APP_ENV=production` for gunicorn with `UVICORN_WORKERS` workers per container.

## Gotchas

- In-flight ticket runs live in the API process — restarting `app` loses them (see [Ticket Operations](ticket_operations.md)).
- Host port collisions with other stacks: every published port is env-overridable (table above).
- The gateway healthcheck curls `/sse/`; `app` waits for `mcp-gateway` to be healthy before starting.
