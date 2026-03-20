# Quickstart

> Minimal steps to get the support AI agent running locally.

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.12+ | Runtime |
| uv | latest | Package manager |
| Docker / Docker Compose | latest | PostgreSQL + Qdrant |
| Node.js / npx | 18+ | MCP stdio servers (optional) |
| Node.js / npm | 20+ | Frontend dashboard (optional) |

## 1. Clone and Install

```bash
git clone <repo-url>
cd support_ai_agent
uv sync
```

## 2. Start Infrastructure

```bash
docker compose up -d postgres qdrant   # PostgreSQL + Qdrant only
```

If not using Docker Compose, ensure:
- PostgreSQL running on `localhost:5432`
- Qdrant running on `localhost:6333`

For full-stack Docker deployment (including the app container), see [Deployment Guide](deployment.md).

## 3. Configure Environment

Create `.env` in the project root:

```ini
APP_ENV=development
LOG_LEVEL=INFO

# PostgreSQL
DB_HOST=127.0.0.1
DB_PORT=5432
DB_USER=postgres
DB_PASS=change_me
DB_NAME=support_agent_db

# Qdrant
QDRANT_URL=http://127.0.0.1:6333

# LLM
OPENAI_API_KEY=sk-...
```

See [configuration.md](configuration.md) for the full env var reference.

## 4. Initialize Database

```bash
# Run Alembic migrations
uv run alembic upgrade head

# Initialize Qdrant collections + indexes
uv run python -m src.utils.init_qdrant
```

## 5. Register a Tenant

```bash
# Register tenant from YAML definition
uv run python src/main.py register-tenant --file data/tenants/fake_client/tenant.yaml

# Seed client context (inventory, baselines, known changes)
uv run python src/main.py seed-context --file data/tenants/fake_client/context.yaml
```

## 6. Run

### CLI Test (Mock Ticket)

```bash
uv run python run_mock.py --file ticket_prueba.txt --fast
```

The `--fast` flag enables `TEST_MODE_FAST` (reduced iterations, fewer retries).

### Web Stack

```bash
# Terminal 1: FastAPI server
uv run uvicorn src.ingestion.api:app --reload

# Terminal 2: Streamlit UI
uv run streamlit run streamlit_app.py
```

### Submit a Ticket via API

```bash
curl -X POST http://localhost:8000/api/v1/webhook/servicenow \
  -H "Content-Type: application/json" \
  -H "X-Customer-ID: fake_client" \
  -d '{"text": "VPN tunnel between site A and site B is down", "severity": "high"}'
```

Returns HTTP 202 with `ticket_id` and `job_id` for polling.

## 7. Frontend Dashboard

The React dashboard provides a web UI for ticket management, run monitoring, and audit logs.

### Dev Mode

Requires the backend running on `:8000` (Vite proxies `/api` and `/health` automatically).

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

### Production Mode (Docker)

```bash
docker compose up -d    # Starts postgres, qdrant, app, frontend
```

- Frontend at `http://localhost:3001` (configurable via `FRONTEND_PORT` in `.env`)
- nginx proxies API requests to the `app` service internally

### First Login

1. Navigate to the frontend URL (`http://localhost:5173` dev, `http://localhost:3001` production)
2. Enter an API key on the login screen (create one via `register-tenant` or the auth API)
3. Dashboard loads with stats, charts, and recent tickets/runs

## See Also

- [Configuration Reference](configuration.md) - Full env var table
- [Deployment Guide](deployment.md) - Docker, production, scaling
- [API Reference](../integrations/api_reference.md) - REST endpoints
