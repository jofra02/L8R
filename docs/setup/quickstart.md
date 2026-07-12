# Quickstart

> Step-by-step guide to get the support AI agent running locally, from zero to submitting your first ticket.

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

For full-stack Docker deployment (including app + frontend containers), see [Deployment Guide](deployment.md).

## 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set these required values:

```ini
# PostgreSQL (must match your docker compose or local instance)
DB_HOST=127.0.0.1
DB_PORT=5432
DB_USER=postgres
DB_PASS=change_me
DB_NAME=support_agent_db

# Qdrant
QDRANT_URL=http://127.0.0.1:6333

# LLM — required for pipeline execution
OPENAI_API_KEY=sk-...
```

See [configuration.md](configuration.md) for the full env var reference.

## 4. Initialize Database

```bash
# Run Alembic migrations (creates all tables including api_keys)
uv run alembic upgrade head

# Initialize Qdrant collections + indexes
uv run python -m src.utils.init_qdrant
```

## 5. Register a Tenant

A tenant represents a customer/organization. All tickets, runs, and audit data are scoped to a tenant.

```bash
# Register tenant from YAML definition
uv run python src/main.py register-tenant --file data/tenants/fake_client/tenant.yaml

# Seed client context (inventory, baselines, known changes)
uv run python src/main.py seed-context --file data/tenants/fake_client/context.yaml
```

This creates a `fake_client` tenant in the database with allowed tools and context data.

## 6. Create an API Key

API keys authenticate **programmatic clients** of the Platform API (ticket ingestion and result polling). They are **not** used by the frontend dashboard — the dashboard uses email + password login (JWT, see step 8). Each key is scoped to a tenant. Access model details: [API Reference — Authentication](../integrations/api_reference.md#authentication).

### Option A: Tenant Key (most common)

Creates a key scoped to a specific tenant. Use this for API integration (e.g., a ticketing system that submits tickets and polls results).

```bash
# Creates a key named "default"
uv run python src/main.py create-tenant-key fake_client

# With an explicit name
uv run python src/main.py create-tenant-key fake_client "CI Pipeline"
```

> API keys carry a fixed permission set: `tickets:write`, `tickets:read`, `runs:read` — enough to submit tickets and poll their runs/reports, nothing else (no inventory, no user management). There is no role argument; broader access requires a JWT **user** with a permission profile (see the [API Keys & Users runbook](../operations/api_keys_and_users.md)).

Output:

```
============================================================
Tenant API Key Created
============================================================
  Tenant:   fake_client
  Key ID:   550e8400-e29b-41d4-a716-446655440000
  Name:     default
  Raw Key:  sk_live_a1b2c3d4e5f6...
============================================================
SAVE THIS KEY — it will not be shown again.
============================================================
```

Copy the `Raw Key` value -- you will need it to authenticate programmatic API requests (step 9).

### Option B: Platform Admin Key

Creates a super-admin key that can impersonate any tenant via the `?customer_id=` query parameter. Only needed for multi-tenant management.

```bash
uv run python src/main.py create-admin-key
```

## 7. Run the Backend

### Option A: Platform API (recommended)

The Platform API serves both the frontend dashboard and programmatic API clients.

```bash
uv run uvicorn src.api.app:app --reload --port 8000
```

Verify it is running:

```bash
curl http://localhost:8000/health
# {"status": "ok", "app": "SupportAI-Agent"}
```

### Option B: CLI Test (no server needed)

For quick testing without starting the API server:

```bash
uv run python run_mock.py --file ticket_prueba.txt --fast
```

The `--fast` flag enables `TEST_MODE_FAST` (reduced iterations, fewer retries).

> **Warning:** `run_mock.py` (and `src/main.py test`) run the **legacy 13-agent graph**, not the current Engineer agent. To exercise the Engineer, submit tickets through the API (Option A).

## 8. Frontend Dashboard

The React dashboard provides a web UI for ticket submission, run monitoring, evidence/hypothesis inspection, and audit logs.

### Dev Mode

Requires the backend running on `:8000` (step 7A). Vite proxies `/api` and `/health` automatically.

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

### Production Mode (Docker)

```bash
docker compose up -d    # Starts postgres, qdrant, app, frontend
```

Frontend available at `http://localhost:3001` (configurable via `FRONTEND_PORT` in `.env`).

### Logging In

The dashboard uses **email + password** (JWT). API keys do not work here.

1. Create an admin user (prints a random one-time password):

   ```bash
   uv run python src/main.py create-admin admin@example.com
   ```

   Alternatively, use the bootstrap admin credentials printed in the migration log on first `alembic upgrade head`.
2. Open the frontend URL (`http://localhost:5173` dev / `http://localhost:3001` production)
3. Log in with the email and one-time password
4. You will be forced to change the password on first login
5. The dashboard loads showing stats, recent tickets, and recent runs

If you get "unauthorized" or the login fails:
- Confirm the backend is running and healthy (`curl http://localhost:8000/health`)
- Confirm you ran `alembic upgrade head` (the auth tables must exist)
- Confirm the user exists (`create-admin` reports an existing email instead of overwriting it)

## 9. Submit Your First Ticket

### Via the Dashboard

1. Log in to the frontend (step 8)
2. Click **New Ticket** in the header
3. Fill in the description, severity, and mode
4. Click **Submit** -- the ticket appears in the list and the pipeline runs in the background
5. Click on the ticket to see its timeline, evidence, hypotheses, plan, and final report

### Via curl

```bash
curl -X POST http://localhost:8000/api/v1/tickets \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk_live_YOUR_KEY_HERE" \
  -d '{
    "text": "Users on subnet 192.168.1.0/24 cannot reach the internet through the firewall",
    "severity": "high",
    "mode": "incident"
  }'
```

Response (HTTP 202):

```json
{
  "status": "accepted",
  "ticket_id": "TKT-abc123",
  "job_id": "550e8400-..."
}
```

Poll the run status:

```bash
curl http://localhost:8000/api/v1/runs?ticket_id=TKT-abc123 \
  -H "Authorization: Bearer sk_live_YOUR_KEY_HERE"
```

Retrieve the final report:

```bash
curl http://localhost:8000/api/v1/tickets/TKT-abc123/report \
  -H "Authorization: Bearer sk_live_YOUR_KEY_HERE"
```

### Via Legacy Webhook (no API key needed)

```bash
curl -X POST http://localhost:8000/api/v1/webhook/servicenow \
  -H "Content-Type: application/json" \
  -H "X-Customer-ID: fake_client" \
  -d '{"text": "VPN tunnel between site A and site B is down", "severity": "high"}'
```

## See Also

- [Configuration Reference](configuration.md) - Full env var table
- [Deployment Guide](deployment.md) - Docker, production, scaling
- [API Reference](../integrations/api_reference.md) - Platform API endpoints
- [Operations Manual](../operations/README.md) - Runbooks for recurring procedures
- [Components Guide](../architecture/components.md) - How each component works
