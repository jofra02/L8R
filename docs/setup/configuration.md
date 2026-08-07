# Configuration Reference

> Complete environment variable reference extracted from `src/config.py`.

## Overview

All configuration is managed through environment variables, loaded via Pydantic Settings from a `.env` file in the project root. The `Settings` class in `src/config.py` defines all available options with their types and defaults.

## Environment Variables

### Application

| Variable | Type | Default | Description |
|---|---|---|---|
| `APP_NAME` | `str` | `SupportAI-Agent` | Application name (used in API title) |
| `APP_ENV` | `str` | `development` | Environment identifier (`development` or `production`) |
| `LOG_LEVEL` | `str` | `INFO` | Python logging level |
| `LOG_DIR` | `str` | `logs` | Directory for application log files |
| `TEST_MODE_FAST` | `bool` | `False` | Reduces iterations (8 vs 15) and retries (1 vs 2) for testing — affects the **legacy pipeline only**, not the Engineer |

### Engineer Agent (Single-Agent Mode)

| Variable | Type | Default | Description |
|---|---|---|---|
| `PIPELINE_MODE` | `str` | `engineer` | `engineer` (current single-agent); `pipeline` is a **deprecated** legacy toggle |
| `LLM_MODEL_ENGINEER` | `str` | `gpt-5.4` | LLM model for the Engineer ReAct agent |
| `LLM_REASONING_EFFORT_ENGINEER` | `str?` | `None` | Engineer-specific reasoning effort (`None` = omit the parameter; some models need an explicit `"none"` to accept function tools) |
| `ENGINEER_MAX_TOOL_CALLS` | `int` | `30` | Maximum tool executions per investigation |
| `ENGINEER_MAX_ITERATIONS` | `int` | `50` | Maximum ReAct loop iterations (LangGraph recursion limit) |
| `ENGINEER_TIMEOUT_SECONDS` | `int` | `600` | Total timeout for the investigation in seconds |

### Device Assessments

| Variable | Type | Default | Description |
|---|---|---|---|
| `ASSESSMENT_ENABLED` | `bool` | `True` | Enable the Device Assessment module |
| `ASSESSMENT_GLOBAL_CONCURRENCY` | `int` | `8` | Max concurrent collection steps overall |
| `ASSESSMENT_DEVICE_CONCURRENCY` | `int` | `3` | Max concurrent steps per device |
| `ASSESSMENT_STEP_TIMEOUT_S` | `int` | `60` | Default per-step timeout (definition YAML can override) |
| `ASSESSMENT_STEP_MAX_ATTEMPTS` | `int` | `2` | Default attempts for retryable errors |
| `ASSESSMENT_MAX_EVIDENCE_BYTES` | `int` | `524288` | Cap on stored evidence payloads (512 KiB) |
| `LLM_MODEL_ASSESSMENT_EVALUATOR` | `str` | `gpt-5-mini` | Model for hybrid/LLM control evaluation |

### PostgreSQL

| Variable | Type | Default | Description |
|---|---|---|---|
| `DB_HOST` | `str` | `localhost` | Database host |
| `DB_PORT` | `int` | `5432` | Database port |
| `DB_USER` | `str` | `postgres` | Database user |
| `DB_PASS` | `str` | `postgres` | Database password |
| `DB_NAME` | `str` | `support_agent_db` | Database name |

### Qdrant (Vector Store)

| Variable | Type | Default | Description |
|---|---|---|---|
| `QDRANT_URL` | `str` | `http://localhost:6333` | Qdrant server URL |
| `QDRANT_API_KEY` | `str?` | `None` | Qdrant API key (required for Qdrant Cloud) |
| `QDRANT_TIMEOUT` | `int` | `60` | Timeout in seconds for Qdrant operations |

### Embedding

| Variable | Type | Default | Description |
|---|---|---|---|
| `EMBEDDING_MODEL` | `str` | `text-embedding-3-small` | OpenAI embedding model name |
| `EMBEDDING_DIMENSIONS` | `int` | `1536` | Embedding vector dimensions |
| `EMBEDDING_BATCH_SIZE` | `int` | `64` | Batch size for embedding API calls |

### Qdrant Search Tuning

| Variable | Type | Default | Description |
|---|---|---|---|
| `QDRANT_HNSW_EF` | `int` | `128` | HNSW ef parameter (higher = more accurate, slower) |
| `QDRANT_INDEXED_ONLY` | `bool` | `False` | Only search indexed vectors |
| `QDRANT_ON_DISK_PAYLOAD` | `bool` | `True` | Store payloads on disk to reduce RAM usage |

### Per-Collection Score Thresholds

Minimum similarity score for results to be returned. Set per collection to tune precision vs recall.

| Variable | Type | Default | Description |
|---|---|---|---|
| `QDRANT_SCORE_TOOL_CATALOG` | `float` | `0.15` | Tool catalog collection threshold |
| `QDRANT_SCORE_ADAPTIVE_FIXES` | `float` | `0.75` | Adaptive fixes collection threshold |
| `QDRANT_SCORE_EVIDENCE` | `float` | `0.7` | Evidence collection threshold |
| `QDRANT_SCORE_KNOWLEDGE_BASE` | `float` | `0.5` | Knowledge base collection threshold |
| `QDRANT_SCORE_RESOLVED_TICKETS` | `float` | `0.0` | Resolved tickets (CBR) threshold |
| `QDRANT_SCORE_TOOL_KNOWLEDGE` | `float` | `0.0` | Tool knowledge collection threshold |

### Hybrid Search

| Variable | Type | Default | Description |
|---|---|---|---|
| `QDRANT_HYBRID_ENABLED` | `bool` | `False` | Enable hybrid (dense + sparse) search |
| `QDRANT_HYBRID_COLLECTIONS` | `list[str]` | `["tool_catalog", "adaptive_fixes", "knowledge_base"]` | Collections to enable hybrid search on |

### MCP (Model Context Protocol)

MCP servers are configured in `data/mcp/servers.yaml` (not in `.env`). The YAML file is loaded at startup by `src/config.py`, which expands `${VAR}` / `${VAR:-default}` placeholders from the environment. See `data/mcp/servers.example.yaml` for full examples and [MCP Gateway architecture](../architecture/mcp_gateway.md) for the bundled gateway.

```yaml
# data/mcp/servers.yaml
servers:
  mcp-gateway:                # the bundled OpenAPI→MCP gateway (mcp_gateway/)
    transport: sse
    url: ${MCP_GATEWAY_URL:-http://localhost:8001/sse}

  network-tools:
    transport: sse
    url: http://10.0.1.50:8001/sse
    vendor: fortinet          # optional — used for tool metadata extraction
    timeout: 45               # optional — declared but NOT enforced by the current client

  filesystem:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
```

**Per-server fields:**

| Field | Required | Description |
|---|---|---|
| `transport` | Yes | `"sse"` (HTTP) or `"stdio"` (subprocess) |
| `url` | SSE only | HTTP endpoint URL |
| `command` | stdio only | Executable name |
| `args` | stdio only | List of command arguments |
| `env` | No | Environment variables dict (stdio only) |
| `vendor` | No | Vendor name for tool metadata (replaces `MCP_SERVER_VENDOR_MAP`) |
| `timeout` | No | Per-server timeout override in seconds — accepted but **not enforced** by the current MCP client |

**Global env var:**

| Variable | Type | Default | Description |
|---|---|---|---|
| `MCP_SERVER_TIMEOUT` | `int` | `30` | Declared but **not enforced** — no per-tool-call timeout is applied today. The Engineer run is bounded by `ENGINEER_TIMEOUT_SECONDS`; assessments enforce per-step `timeout_s` (`ASSESSMENT_STEP_TIMEOUT_S`) via `execute_mcp_tool` |

### MCP Gateway Admin API (inventory sync)

Used by the app to propagate managed devices/tenants to the gateway. Disabled unless URL **and** token are set.

| Variable | Type | Default | Description |
|---|---|---|---|
| `MCP_GATEWAY_ADMIN_URL` | `str?` | `http://localhost:8001` | Gateway admin API base URL (compose overrides to `http://mcp-gateway:8000`) |
| `MCP_GATEWAY_ADMIN_TOKEN` | `str?` | `None` | `X-Admin-Token` shared secret (compose wires it from `GATEWAY_ADMIN_TOKEN`) |
| `MCP_GATEWAY_ADMIN_TIMEOUT` | `float` | `10.0` | Admin API request timeout in seconds |

### Outbound Notifications (n8n webhook)

Disabled unless `N8N_WEBHOOK_URL` is set. See [Outbound Notifications](../notifications.md).

| Variable | Type | Default | Description |
|---|---|---|---|
| `N8N_WEBHOOK_URL` | `str?` | `None` | n8n webhook endpoint for `ticket.ingested` / `run.completed` events |
| `NOTIFICATION_TIMEOUT` | `float` | `10.0` | Webhook POST timeout in seconds |
| `NOTIFICATION_AUTH_HEADER_NAME` | `str?` | `None` | Optional auth header name (e.g. `X-Webhook-Token`) |
| `NOTIFICATION_AUTH_HEADER_VALUE` | `str?` | `None` | Optional auth header value |

### LLM Profiles (Legacy Multi-Agent Mode)

> These settings only apply when `PIPELINE_MODE=pipeline`. In engineer mode, only `LLM_MODEL_ENGINEER` is used.

| Variable | Type | Default | Description |
|---|---|---|---|
| `LLM_MODEL_CLASSIFIER` | `str` | `gpt-5.4-nano` | Model for domain classification |
| `LLM_MODEL_CONTEXT` | `str` | `gpt-5.4-nano` | Model for context agent |
| `LLM_MODEL_MAPPER` | `str` | `gpt-5.4-nano` | Model for component mapping |
| `LLM_MODEL_SUPERVISOR` | `str` | `gpt-5.4-mini` | Model for supervisor routing (unused -- routing is deterministic) |
| `LLM_MODEL_EVIDENCE_COLLECTOR` | `str` | `gpt-5.4-mini` | Model for intent generation + tool argument binding |
| `LLM_MODEL_ENRICHER` | `str` | `gpt-5.4-mini` | Model for fact/topology extraction |
| `LLM_MODEL_HYPOTHESIS` | `str` | `gpt-5.4` | Model for hypothesis generation + path analysis |
| `LLM_MODEL_INVESTIGATOR` | `str` | `gpt-5.4` | Model for investigation + adaptive executor diagnosis |
| `LLM_MODEL_PLANNER` | `str` | `gpt-5.4` | Model for resolution plan generation |
| `LLM_MODEL_RESPONSE` | `str` | `gpt-5.4-nano` | Model for final report generation |
| `LLM_MODEL_ADAPTIVE_FIX` | `str` | `gpt-5-nano` | Model for adaptive executor self-healing |
| `LLM_REASONING_EFFORT` | `str?` | `None` | Reasoning effort level for compatible models (`low`, `medium`, `high`, or `null` to skip) |
| `LLM_TEMPERATURE_DEFAULT` | `float` | `0.0` | Default temperature for all LLM calls |

### Safety and Governance

| Variable | Type | Default | Description |
|---|---|---|---|
| `SAFETY_BLOCKED_KEYWORDS` | `list[str]` | See below | Keywords that block tool registration/execution (scanned against tool names **and** string argument values) |
| `SAFETY_BLOCKED_NAME_KEYWORDS` | `list[str]` | See below | Mutating verbs blocked in **tool names only** (kept separate so substrings like `createdBy` in argument values stay legal); mirrored in `mcp_gateway/scripts/convert_fortiedr_specs.py` |

Default `SAFETY_BLOCKED_KEYWORDS`: `debug flow`, `sniffer`, `packet capture`, `pcap`, `tcpdump`, `wireshark`, `execute`, `configure`, `set `, `edit `, `delete`, `rm `, `shutdown`, `reboot`, `drop database`, `truncate`, `format`, `destroy`, `purge`, `kill `, `deploy`, `push`, `publish`, `migrate`, `alter `, `grant `, `revoke `. Note the **trailing space** on `set `, `edit `, `rm `, `kill `, `alter `, `grant `, `revoke ` — it prevents false positives on words like "settings" or "settle".

Default `SAFETY_BLOCKED_NAME_KEYWORDS`: `update`, `create`, `upload`, `upgrade`, `isolate`, `uninstall`, `remediate`, `terminate`, `set_`, `reset`, `assign`, `clone`, `transfer`, `import`, `toggle`, `release`, `move`, `stop`.

### Tool Catalog

| Variable | Type | Default | Description |
|---|---|---|---|
| `TOOL_CATALOG_REINDEX_CAP` | `int` | `200` | Max CHANGED tools re-embedded/re-classified per startup; excess deferred to the next startup (see [Tool Catalog runbook](../operations/tool_catalog.md)) |
| `TOOL_CATEGORY_TIER1_MIN` | `int` | `3` | Minimum tier-1 candidates in the legacy `ToolSelector` category search |
| `TOOL_CATEGORY_TIER2_MIN` | `int` | `3` | Minimum tier-2 candidates in the legacy `ToolSelector` category search |

### Langfuse Observability

| Variable | Type | Default | Description |
|---|---|---|---|
| `LANGFUSE_ENABLED` | `bool` | `False` | Enable/disable Langfuse integration |
| `LANGFUSE_PUBLIC_KEY` | `str?` | `None` | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | `str?` | `None` | Langfuse secret key |
| `LANGFUSE_HOST` | `str` | `http://localhost:3000` | Langfuse server URL |
| `LANGFUSE_SAMPLE_RATE` | `float` | `1.0` | Trace sampling rate (0.0-1.0) |
| `LANGFUSE_FLUSH_AT` | `int` | `15` | Batch size before flushing to Langfuse |
| `LANGFUSE_FLUSH_INTERVAL` | `int` | `5` | Flush interval in seconds |

### JWT / Authentication

| Variable | Type | Default | Description |
|---|---|---|---|
| `JWT_SECRET_KEY` | `str` | `CHANGE-ME-IN-PRODUCTION` | JWT signing secret (must change for production) |
| `JWT_ALGORITHM` | `str` | `HS256` | JWT algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `int` | `30` | Access token expiry |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `int` | `7` | Refresh token expiry |
| `PASSWORD_MIN_LENGTH` | `int` | `12` | Minimum password length |
| `PASSWORD_REQUIRE_UPPERCASE` | `bool` | `True` | Require uppercase characters |
| `PASSWORD_REQUIRE_SYMBOL` | `bool` | `True` | Require symbol characters |
| `BOOTSTRAP_ADMIN_EMAIL` | `str` | `admin@localhost` | First super admin email |

### API Keys

| Variable | Type | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | `str?` | `None` | OpenAI API key (required for LLM calls) |

## Configuration Loading

Settings are loaded in this order (later overrides earlier):
1. Default values in `Settings` class
2. `.env` file in project root (`env_file_encoding="utf-8"`)
3. Environment variables

The `extra="ignore"` setting means unknown env vars are silently ignored.

## Docker Compose

### Env Var Centralization

All configuration lives in a single `.env` file. The `DB_*` variables are the canonical database credentials — `docker-compose.yml` maps them to the postgres container's expected `POSTGRES_*` vars automatically:

```yaml
# docker-compose.yml (excerpt)
postgres:
  environment:
    POSTGRES_USER: ${DB_USER:-postgres}      # ← reads from DB_USER
    POSTGRES_PASSWORD: ${DB_PASS:-change_me}  # ← reads from DB_PASS
    POSTGRES_DB: ${DB_NAME:-support_agent_db} # ← reads from DB_NAME
```

There is no need to define `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB` in `.env`. Only `DB_*` vars are needed.

Inside containers, `DB_HOST` and `QDRANT_URL` are overridden to Docker service names (`postgres`, `qdrant`).

### Running the Stack

```bash
# Basic stack (postgres, qdrant, mcp-gateway, app, frontend)
docker compose up -d

# With Langfuse observability
docker compose --profile observability \
  -f docker-compose.yml \
  -f docker-compose.observability.yml \
  up -d

# View logs
docker compose logs -f app

# Rebuild after code changes
docker compose build app frontend
docker compose up -d
```

### Docker Compose Port Overrides

These variables only affect `docker-compose.yml` port mappings, not the application:

| Variable | Default | Service |
|---|---|---|
| `APP_PORT` | `8000` | Backend API |
| `FRONTEND_PORT` | `3001` | Frontend (nginx) |
| `POSTGRES_PORT` | `5432` | PostgreSQL |
| `QDRANT_PORT` | `6333` | Qdrant HTTP |
| `QDRANT_GRPC_PORT` | `6334` | Qdrant gRPC |
| `MCP_GATEWAY_PORT` | `8001` | MCP Gateway (SSE; container port 8000) |
| `MCP_GATEWAY_LOG_LEVEL` | `info` | MCP Gateway log level |
| `LANGFUSE_PORT` | `3000` | Langfuse |
| `UVICORN_WORKERS` | `1` (dev) / `2` (prod) | Backend workers |

The `mcp-gateway` service additionally reads `INVENTORY_MASTER_KEY`, `GATEWAY_ADMIN_TOKEN`, optional `DEFAULT_TENANT`, and the upstream HTTP timeouts `GATEWAY_HTTP_TIMEOUT` (read, default `30`s) / `GATEWAY_HTTP_CONNECT_TIMEOUT` (default `5`s) from `.env` (see [Deployment — MCP Servers](deployment.md#mcp-servers) and [Gateway Secrets](../operations/gateway_secrets.md)); appliance packs may override the timeouts per pack via `http_timeout`/`http_connect_timeout` in their `manifest.yaml`. The `cloudflared` service (profile `tunnel`) needs `CLOUDFLARE_TUNNEL_TOKEN`.

## See Also

- [Quickstart](quickstart.md) - Minimal setup steps
- [Deployment Guide](deployment.md) - Production configuration
- [Safety and Governance](../architecture/safety_and_governance.md) - Tool governance details
