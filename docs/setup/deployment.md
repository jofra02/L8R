# Deployment Guide

> Docker Compose deployment, service configuration, and production hardening.

## Architecture

The full stack consists of five services:

```
    Browser
      |
      v
+---------------------+
| frontend (:3001)    |
| nginx (SPA + proxy) |
+----------+----------+
           |  /api, /health
           v
+---------------------+
|    app (:8000)      |    .env
|  FastAPI + Agent    |<----------
+---+-------------+---+
    |             |
+---v--------+  +-v--------------+
| postgres   |  | qdrant         |
| (:5432)    |  | (:6333/:6334)  |
+------------+  +----------------+

    Optional:
+------------+
| langfuse   |  (--profile observability)
| (:3000)    |
+------------+
```

| Service | Port | Purpose |
|---|---|---|
| `frontend` | 3001 | React dashboard (nginx: SPA fallback + API proxy) |
| `app` | 8000 | Platform API + LangGraph pipeline |
| `postgres` | 5432 | Case state, audit logs, checkpoints |
| `qdrant` | 6333 (HTTP), 6334 (gRPC) | Vector KB, evidence, tool catalog, CBR |
| `langfuse` | 3000 | Observability traces (optional) |

External dependencies (not containerized):
- **MCP servers** -- read-only tool providers, deployed near target infrastructure
- **OpenAI-compatible API** -- LLM inference endpoint

## Quick Deploy (Docker Compose)

> For the non-Docker development path see the [Quickstart](quickstart.md).

### Prerequisites

- Docker Engine 24+ with Compose V2
- An OpenAI-compatible API key

### Steps

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd support_ai_agent

# 2. Create .env from template
cp .env.example .env
# Edit .env: set OPENAI_API_KEY, POSTGRES_PASSWORD, DB_PASS

# 3. Start all services
docker compose up -d

# 4. Verify
docker compose ps          # All services "healthy"
curl http://localhost:8000/health   # {"status": "ok"}
```

The entrypoint script automatically runs:
1. `alembic upgrade head` -- database migrations
2. `python -m src.utils.init_qdrant` -- Qdrant collection initialization (idempotent)
3. `uvicorn` -- application server

### With Langfuse Observability

Langfuse requires a bootstrap sequence — the API keys are generated **after** Langfuse is running, so the app starts with tracing disabled first.

#### 1. Generate secrets and configure `.env`

```bash
# Generate three secrets
openssl rand -base64 32   # → LANGFUSE_NEXTAUTH_SECRET
openssl rand -base64 32   # → LANGFUSE_SALT
openssl rand -base64 32   # → JWT_SECRET_KEY (if not already set)
```

Set these in `.env`:

```env
LANGFUSE_ENABLED=false                          # disabled until keys are obtained
LANGFUSE_HOST=http://localhost:3000              # docker-compose overrides to http://langfuse:3000
LANGFUSE_DB=langfuse
LANGFUSE_NEXTAUTH_SECRET=<generated-secret>
LANGFUSE_SALT=<generated-salt>
```

#### 2. Create the Langfuse database

Langfuse uses a separate database in the same postgres instance. The postgres container only auto-creates the app database (`DB_NAME`), so create the Langfuse DB manually:

```bash
docker compose up -d postgres
docker compose exec postgres pg_isready -U ${DB_USER:-postgres}
docker compose exec postgres createdb -U ${DB_USER:-postgres} langfuse
```

#### 3. Start the full stack

Compose is idempotent -- postgres from Step 2 stays running; only new services are started.

```bash
docker compose --profile observability \
  -f docker-compose.yml \
  -f docker-compose.observability.yml \
  up -d
```

> **Without the override file**: `docker compose --profile observability up -d` also works, but the `app` container starts without waiting for Langfuse. The override file (`docker-compose.observability.yml`) adds `depends_on langfuse: condition: service_started` to the `app` service, ensuring Langfuse is up before the app starts.

Verify all services:

```bash
docker compose ps
curl http://localhost:8000/health    # backend
curl http://localhost:3001           # frontend
curl http://localhost:3000           # langfuse UI
```

#### 4. Create Langfuse project and API keys

1. Open `http://<your-host>:3000` in your browser
2. Create an account (first user becomes admin)
3. Create a new **project**
4. Go to **Settings → API Keys** → create new keys
5. Copy the **Public Key** (`pk-lf-...`) and **Secret Key** (`sk-lf-...`)

#### 5. Enable tracing

Update `.env`:

```env
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-<your-key>
LANGFUSE_SECRET_KEY=sk-lf-<your-key>
```

Restart only the app:

```bash
docker compose restart app
```

Submit a test ticket — traces should appear in the Langfuse dashboard.

## Service Configuration

### PostgreSQL

The compose file uses `postgres:16-alpine`. The `DB_*` variables are the canonical credentials — docker-compose maps them to the postgres container automatically (`DB_USER` → `POSTGRES_USER`, etc.):

| Variable | Default | Description |
|---|---|---|
| `DB_USER` | `postgres` | Database user (mapped to `POSTGRES_USER` in compose) |
| `DB_PASS` | `change_me` | Database password (mapped to `POSTGRES_PASSWORD`) |
| `DB_NAME` | `support_agent_db` | Database name (mapped to `POSTGRES_DB`) |
| `DB_HOST` | `localhost` | Overridden to `postgres` inside compose |
| `DB_PORT` | `5432` | Database port |

**Managed database alternative**: Set `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`, `DB_NAME` to point at your managed instance (RDS, Cloud SQL, Azure Database). Remove or stop the `postgres` service in compose.

**SSL**: For managed databases requiring SSL, configure via SQLAlchemy connect args in `src/core/orm.py`.

### Qdrant

The compose file uses `qdrant/qdrant:v1.14.0` with persistent storage.

| Variable | Docker Default | Description |
|---|---|---|
| `QDRANT_URL` | `http://qdrant:6333` (overridden in compose) | HTTP API URL |
| `QDRANT_API_KEY` | `None` | API key (required for Qdrant Cloud) |
| `QDRANT_TIMEOUT` | `60` | Operation timeout in seconds |

**Qdrant Cloud alternative**: Set `QDRANT_URL` and `QDRANT_API_KEY` to your cloud cluster. Remove or stop the `qdrant` service.

**Backups**: See the [Backup & Restore runbook](../operations/backup_restore.md) (PostgreSQL + all Qdrant collections + evidence store).

### Application

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Set to `production` for gunicorn with uvicorn workers |
| `UVICORN_WORKERS` | `1` (dev), `2` (prod) | Number of worker processes |
| `APP_PORT` | `8000` | Host port mapping |

The entrypoint (`scripts/entrypoint.sh`) selects the server based on `APP_ENV`:
- **development**: `uvicorn` with configurable workers
- **production**: `gunicorn` with `UvicornWorker` class

### Frontend

The compose file includes a `frontend` service that builds from `./frontend`.

- **Multi-stage Dockerfile**: `node:22-alpine` builds the React app, then copies the `dist/` output into `nginx:alpine`
- **nginx.conf**: SPA fallback (`try_files $uri $uri/ /index.html`) + reverse proxy for `/api/` and `/health` to `app:8000`
- **Port**: `FRONTEND_PORT` env var (default `3001`), maps to nginx port 80 inside the container
- **Dependency**: `depends_on: app` with `condition: service_healthy` — the frontend starts only after the API is healthy

### MCP Servers

MCP servers provide read-only tool access. The platform ships its own: the **MCP Gateway** (`mcp_gateway/`), a generic OpenAPI→MCP server included in this compose stack as the `mcp-gateway` service (see [MCP Gateway architecture](../architecture/mcp_gateway.md)). Additional external MCP servers can be registered alongside it — e.g. when they must be deployed near the target infrastructure.

Configure in `data/mcp/servers.yaml`. `${VAR:-default}` placeholders are expanded from the environment:

```yaml
servers:
  mcp-gateway:
    transport: sse
    url: ${MCP_GATEWAY_URL:-http://localhost:8001/sse}   # compose sets MCP_GATEWAY_URL

  network-tools:
    transport: sse
    url: http://mcp-host:8001/sse
    vendor: fortinet        # optional — used for tool metadata extraction
    timeout: 45             # optional — overrides MCP_SERVER_TIMEOUT
```

The `mcp-gateway` compose service needs `INVENTORY_MASTER_KEY` and `ACTIVE_CUSTOMER_ID` in `.env`, and mounts `./mcp_gateway/inventory` read-only (device credentials never enter the image).

See `data/mcp/servers.example.yaml` for SSE and stdio transport examples. The YAML is loaded at startup by `src/config.py`; see [Configuration > MCP](configuration.md#mcp-model-context-protocol) for the full field reference.

**Docker networking note**: If MCP servers run on the Docker host, use `host.docker.internal` (Docker Desktop) or the host's IP address as the hostname. `localhost` inside the container refers to the container itself.

### Langfuse

Langfuse runs under the `observability` profile and shares the PostgreSQL instance (separate database). See [With Langfuse Observability](#with-langfuse-observability) above for the full bootstrap sequence.

| Variable | Default | Description |
|---|---|---|
| `LANGFUSE_ENABLED` | `false` | Enable trace collection in the app |
| `LANGFUSE_PUBLIC_KEY` | — | Obtained from Langfuse UI after project creation |
| `LANGFUSE_SECRET_KEY` | — | Obtained from Langfuse UI after project creation |
| `LANGFUSE_HOST` | `http://localhost:3000` | Overridden to `http://langfuse:3000` in compose |
| `LANGFUSE_DB` | `langfuse` | Langfuse database name (must be created manually) |
| `LANGFUSE_NEXTAUTH_SECRET` | (must generate) | `openssl rand -base64 32` |
| `LANGFUSE_SALT` | (must generate) | `openssl rand -base64 32` |
| `LANGFUSE_PORT` | `3000` | Host port mapping |

> **Note**: The compose file always sets `LANGFUSE_HOST=http://langfuse:3000` in the `app` service environment, even when the Langfuse container is not running. This is harmless -- when `LANGFUSE_ENABLED=false`, the Langfuse client is never initialized and no connection is attempted.

**Langfuse Cloud alternative**: Set `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY` to your cloud project values. Do not start the `langfuse` profile.

## Initialization and Data

### Database Migrations

Handled automatically by the entrypoint. To run manually:

```bash
docker compose exec app python -m alembic upgrade head
```

### Qdrant Collections

Handled automatically by the entrypoint (`init_qdrant` is idempotent). To run manually:

```bash
docker compose exec app python -m src.utils.init_qdrant
```

### Tenant Registration

After services are running, register tenants:

```bash
docker compose exec app python src/main.py register-tenant --file data/tenants/<tenant>/tenant.yaml
docker compose exec app python src/main.py seed-context --file data/tenants/<tenant>/context.yaml
```

### Knowledge Base Seeding

Populate KB collections via the API or CLI tooling as documented in the tenant setup.

## Health Checks

All services define Docker health checks:

| Service | Check | Interval |
|---|---|---|
| `postgres` | `pg_isready` | 5s |
| `qdrant` | `GET /readyz` | 5s |
| `app` | `GET /health` | 10s (30s start period) |
| `frontend` | `curl -sf http://localhost:80/` | 10s |

The `app` service uses `depends_on` with `condition: service_healthy` for `postgres` and `qdrant`, ensuring migrations only run after dependencies are ready.

### Manual Verification

```bash
# Service status
docker compose ps

# Application health
curl http://localhost:8000/health

# PostgreSQL
docker compose exec postgres pg_isready

# Qdrant
curl http://localhost:6333/readyz
```

## Production Hardening

### Reverse Proxy

Place nginx, Caddy, or a cloud load balancer in front of the `app` service. The proxy should:
- Terminate TLS
- Validate/inject `X-Customer-ID` header (tenant isolation)
- Rate-limit incoming webhook requests

### Secrets Management

- Never commit `.env` to version control
- Use Docker secrets, Vault, or cloud secret managers for `OPENAI_API_KEY`, `DB_PASS`, and Langfuse keys
- Generate strong values for `LANGFUSE_NEXTAUTH_SECRET` and `LANGFUSE_SALT`

### Resource Limits

Add resource constraints in `docker-compose.yml` or your orchestrator:

```yaml
services:
  app:
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 2G
```

### Logging

- Set `LOG_LEVEL=WARNING` in production
- Use Docker's logging drivers to ship logs to your aggregation platform
- Langfuse captures LLM traces separately from application logs

### Security

- All tool execution is read-only; write actions require HITL approval via LangGraph interrupt
- Tenant isolation is enforced at the query level -- every DB and Qdrant query filters by `customer_id`
- Rotate API keys regularly (`OPENAI_API_KEY`, `LANGFUSE_SECRET_KEY`, `QDRANT_API_KEY`)

## Scaling

### Horizontal API Scaling

Each pipeline execution is independent per ticket -- no shared in-memory state between requests. Scale the `app` service:

```bash
docker compose up -d --scale app=3
```

Place a load balancer in front of the scaled instances.

### Database Scaling

- PostgreSQL: use a managed service with read replicas for audit log queries
- Qdrant: scale independently based on collection size and query volume

### Task Queue

Background task execution uses FastAPI `BackgroundTasks` (single-process). For high throughput, consider Celery or a dedicated task queue.

## Configurable Parameters

See [Configuration Reference](configuration.md) for the full environment variable table. Production-critical variables:

| Variable | Why |
|---|---|
| `APP_ENV=production` | Switches to gunicorn |
| `UVICORN_WORKERS` | Match to available CPU cores |
| `LOG_LEVEL=WARNING` | Reduce log noise |
| `OPENAI_API_KEY` | Required for LLM inference |
| `DB_PASS` | Must be strong (mapped to postgres container automatically) |
| `QDRANT_API_KEY` | Required if using Qdrant Cloud |
| `LANGFUSE_ENABLED` | Enable trace collection |

## See Also

- [Quickstart](quickstart.md) - Local development setup
- [Configuration Reference](configuration.md) - All env vars
- [Observability](../architecture/observability.md) - Langfuse integration details
