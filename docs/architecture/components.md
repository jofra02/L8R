# Components Guide

> How each component of the platform works — deeper than the [overview](overview.md), shallower than the code. Each section: what it is, how it works, where the code lives, and related docs.

Contents: [Ingestion](#1-ingestion) · [Engineer Agent](#2-engineer-agent) · [CapabilityRegistry & MCP Client](#3-capabilityregistry--mcp-client) · [Safety & Governance](#4-safety--governance) · [Data Layer](#5-data-layer) · [API & RBAC](#6-api--rbac) · [Frontend](#7-frontend) · [MCP Gateway](#8-mcp-gateway) · [Observability](#9-observability) · [Legacy Pipeline](#10-legacy-pipeline)

---

## 1. Ingestion

**What it is**: the front door — turns an HTTP request into a persisted ticket and a running investigation.

**How it works**: two entry points feed the same path: `POST /api/v1/tickets` (API-key auth) and the legacy `POST /api/v1/webhook/{source}` (`X-Customer-ID` header). `IngestionService.ingest_webhook` hands the raw payload to `GenericNormalizer`, which detects the ticket `mode` (incident / change / validation / inquiry) and severity from keywords when not provided, persists a `TicketORM` row, and creates an `AgentRun`. Execution then launches as a **fire-and-forget asyncio task** in the API process (`run_pipeline_background`), tracked in an in-memory registry — the request returns `202 {ticket_id, job_id}` immediately. Because the task lives in-process, an API restart loses in-flight runs (there is no durable queue). A `PollerService` scaffold exists for pull-based sources, but only a mock poller is implemented.

**Code**: `src/ingestion/service.py`, `src/ingestion/normalizers/`, `src/api/routers/tickets.py`.

**Related**: [Ticket Operations runbook](../operations/ticket_operations.md) · [API Reference](../integrations/api_reference.md)

---

## 2. Engineer Agent

**What it is**: the brain — a single ReAct agent that investigates tickets end to end, replacing the old 13-agent pipeline.

**How it works**: the LangGraph graph is deliberately trivial (`src/agent_graph_v2.py`: one `engineer` node → END); the real loop runs inside the node via `langgraph.prebuilt.create_react_agent`, bounded by `ENGINEER_MAX_ITERATIONS` and an `asyncio` timeout (`ENGINEER_TIMEOUT_SECONDS`). The agent holds exactly **6 meta-tools** (factory: `create_engineer_tools`, with runtime context bound by closure and an `EngineerToolState` accumulating evidence/topology across calls):

| Tool | Role |
|---|---|
| `query_client_db` | Load the tenant's `ClientContext` (inventory, dependencies, baselines, known changes) |
| `load_domain_skill` | Inject a domain methodology on demand (`DOMAIN_SKILL_MAP`, 18 keywords → 3 skill files) |
| `search_tool_catalog` | Semantic search over the Qdrant tool catalog |
| `search_knowledge_base` | Search the tenant's KB (runbooks, vendor docs) |
| `execute_tool` | Run one MCP tool: safety check → tenant scope → dedup → execute → store evidence |
| `submit_findings` | Emit the structured result (summary, hypotheses, facts, plan, case_status) |

The **skills system** keeps the base investigation methodology permanently in the system prompt and loads domain skills on demand. The agent must finish with `submit_findings`; the node converts the raw dicts into typed `GlobalState` models and synthesizes a `ScoringResult` for the frontend. A fallback extractor covers runs where the agent never called it.

**Config knobs**: `LLM_MODEL_ENGINEER`, `ENGINEER_MAX_TOOL_CALLS`, `ENGINEER_MAX_ITERATIONS`, `ENGINEER_TIMEOUT_SECONDS`.

**Code**: `src/agents/engineer.py`, `engineer_tools.py`, `engineer_prompts.py`, `src/agents/skills/`.

**Related**: [Engineer Agent doc](../agents/engineer.md) (full detail)

---

## 3. CapabilityRegistry & MCP Client

**What it is**: the bridge between the agent and its tools — discovers, filters, indexes, and executes MCP tools.

**How it works**: at API startup the registry loads in-process capability packs (`src/capabilities/`, currently a stub) and then connects to every server in `data/mcp/servers.yaml` via `MCPClient` (stdio or SSE; connections are per-call, not pooled). Each remote tool is wrapped as an `ExternalToolWrapper` and passed through the **safety filter** — of the **2776** tools the MCP Gateway exposes, **2220** survive and get registered. Indexing into Qdrant `tool_catalog` is **diff-based**: only tools missing from the index are embedded and sent through an **LLM classification pass** (IT-domain categories, discovery tier, identifier metadata, batches of 15); when nothing changed the startup logs `tool_catalog up to date`. Vendor attribution comes from the `vendor:` field in servers.yaml or name-pattern matching (`fgt`/`forti` → fortinet). At run time, `execute_tool` resolves the tool from the registry and calls it directly — no retry middleware in engineer mode.

**Code**: `src/core/registry.py`, `src/mcp/client.py`, `data/mcp/servers.yaml`, `src/core/interfaces.py` (`CapabilityPackInterface`).

**Related**: [MCP Tools](../integrations/mcp_tools.md) · [Tool Catalog runbook](../operations/tool_catalog.md)

---

## 4. Safety & Governance

**What it is**: the guarantees that the agent only ever reads.

**How it works**: the keyword blocklist (config-driven) is applied **twice** — at registration (unsafe tools never enter the registry or the catalog: the 2776→2220 filter) and at execution (`is_safe_tool` inside `execute_tool`, checking name and arguments). It has two parts: `SAFETY_BLOCKED_KEYWORDS` (scanned against tool names **and** string argument values) and `SAFETY_BLOCKED_NAME_KEYWORDS` (mutating verbs like `update`/`create`/`isolate`, scanned against names only — argument values legitimately contain substrings like `lastUpdateTime`). Per-tenant `CapabilityScope` rows add an allowlist layer (`is_tool_allowed_for_tenant`, glob patterns like `fgt74_*`; fail-open when a tenant has no scopes). Write actions are never executed — the Engineer's plan *proposes* them for humans. HITL approval gates are planned, not implemented.

**Code**: `src/core/safety.py`, `src/core/registry.py:_is_safe`, `src/config.py` (keyword list).

**Related**: [Safety and Governance](safety_and_governance.md)

---

## 5. Data Layer

**What it is**: three stores with strict `customer_id` isolation.

**How it works**:
- **PostgreSQL** (async SQLAlchemy + Alembic): control plane (`platform_tenants`, `capability_scopes`, users/RBAC/API keys) and data plane (`tickets`, `agent_runs`, `agent_events`, `tool_calls_audit`, `evidence_refs`, `client_contexts`). Every data-plane table carries an indexed `customer_id`.
- **Qdrant** (6 collections): `knowledge_base`, `evidence`, `tool_catalog` (global, `__global__` sentinel), `resolved_tickets`, plus legacy-pipeline collections `tool_knowledge` and `adaptive_fixes`. All searches filter by `customer_id`.
- **Evidence store** (`data/evidence/`): immutable, content-addressable JSON blobs (SHA-256 dedup), triple-tracked — blob on disk, vector in Qdrant, metadata row in Postgres.

**Code**: `src/core/orm.py`, `qdrant.py`, `evidence_store.py`, `context_store.py`, `src/alembic/`.

**Related**: [Data Layer](data_layer.md) (full schema) · [Backup & Restore runbook](../operations/backup_restore.md)

---

## 6. API & RBAC

**What it is**: the FastAPI platform API — 9 routers, ~77 endpoints under `/api/v1`.

**How it works**: two credential types with different power. **API keys** (`sk_live_...`) always resolve to role `operator` with `tickets:write` — machine ticket ingestion only. **JWT users** carry the `viewer < operator < tenant_admin < platform_admin` hierarchy plus fine-grained permission profiles (`users:manage`, `inventory:read`, ...) and are required for all administration. Routers, one line each: `auth` (login/JWT/keys), `tickets` (submit + results), `runs` (status/timeline/tool-calls), `audit` (logs), `users` / `profiles` / `assignments` (RBAC), `tenants` (lifecycle + capability scopes), `inventory` (CRUD over the tenant's `ClientContext` — the same data `query_client_db` reads).

**Code**: `src/api/app.py`, `src/api/routers/`, `src/api/services/auth_service.py`.

**Related**: [API Reference](../integrations/api_reference.md) · [API Keys & Users runbook](../operations/api_keys_and_users.md)

---

## 7. Frontend

**What it is**: the React dashboard (`frontend/`, React 19 + Vite + TanStack Query, served by nginx in compose at `:3001`).

**How it works**: JWT login (with forced password change on first login), then views for: dashboard (run stats), tickets (submit, list, detail with report/hypotheses/facts/plan/evidence tabs), runs (timeline + tool-call audit), inventory (CRUD over the tenant context), audit logs, settings (users/profiles/tenants/keys for admins), and a global/platform view. It consumes the platform API exclusively; in dev, Vite proxies `/api` to `:8000`. A legacy `streamlit_app.py` UI still exists at the repo root but the React app is the current dashboard.

**Code**: `frontend/src/pages/{tickets,runs,inventory,audit,settings,global}/`, `DashboardPage.tsx`.

---

## 8. MCP Gateway

**What it is**: the hands — a separate service (`mcp_gateway/`, own uv project + container) that turns vendor OpenAPI specs into MCP tools.

**How it works**: at startup it discovers **appliance packs** under `vendors/<vendor>/<appliance>/` (`fortinet/fortigate` — 62 FortiOS specs; `fortinet/fortiedr` — 26 generated FortiEDR specs). For each pack, the spec pipeline applies generic schema fixes plus vendor hooks, sanitizes operation ids, injects an optional `device` routing header into every operation, and mounts everything as `FastMCP` servers — producing tool names `{prefix}_{group}_{spec}_{operation}` (e.g. `fgt74_monitor_sys_get_status`), **2776** in total, frozen against `baseline_tools.txt`. A `RoutingClient` routes each call to the right device from the tenant's inventory (Fernet-encrypted tokens, `INVENTORY_MASTER_KEY`), swapping host and auth headers per request via the pack's `AuthStrategy`; without a `device` header the `primary: true` device is used. Exposed over SSE at `/sse/` (no auth yet — trusted networks only); the agent consumes it through `servers.yaml`.

**Code**: `mcp_gateway/gateway/` (engine), `mcp_gateway/vendors/` (packs), `mcp_gateway/inventory/` (devices, gitignored).

**Related**: [MCP Gateway architecture](mcp_gateway.md) · [Gateway Operations](../operations/gateway_operations.md) / [Secrets](../operations/gateway_secrets.md) / [Upgrades](../operations/gateway_upgrades.md)

---

## 9. Observability

**What it is**: Langfuse tracing over every run.

**How it works**: a trace per run (`run_id`); the `audit_node` wrapper opens an `agent:engineer` span, and a LangChain `CallbackHandler` scoped to that span auto-instruments every LLM turn and tool call inside the ReAct loop (tokens, latency, args). Sampling via `LANGFUSE_SAMPLE_RATE`; graceful no-op when disabled. Langfuse itself runs as a compose service under the `observability` profile.

**Code**: `src/core/langfuse_integration.py`, `src/agents/audit_wrapper.py`.

**Related**: [Observability](observability.md) · [Docker Compose runbook](../operations/docker_compose.md)

---

## 10. Legacy Pipeline

The original architecture was a 13-agent LangGraph pipeline (classifier, mapper, evidence collector, enricher, hypothesis, scoring, supervisor, ...) with a 4-phase ToolSelector and a self-healing AdaptiveExecutor. It survives in-tree (`src/agents/*.py` legacy modules, `src/agent_graph.py`, `src/core/tool_selector.py`, `adaptive_executor.py`) gated behind the deprecated `PIPELINE_MODE=pipeline` toggle — and is still what `main.py test` and `run_mock.py` run unconditionally. Its documentation is archived under [docs/legacy/](../legacy/agents/README.md), including the former "current" docs [tool_selection_pipeline.md](../legacy/architecture/tool_selection_pipeline.md) and [adaptive_execution.md](../legacy/architecture/adaptive_execution.md).
