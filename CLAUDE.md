# CLAUDE.md — support_ai_agent

## Project Overview

Single-agent L1/L2 technical support framework. Receives IT support tickets (incidents/changes), runs a single Engineer ReAct agent that autonomously investigates using 6 meta-tools, then produces structured findings — without executing any write actions on external systems. Domain-agnostic: works across networking, infrastructure, cloud, application, database, security, and any IT domain.

Second product module: **Device Assessments** (`src/assessments/`) — deterministic, definition-driven security assessments over managed devices (first: FortiGate). Versioned YAML definitions pin collection steps and controls; the LLM never chooses tools (it only assists `hybrid`/`llm` controls over pre-collected evidence, schema-validated + citation-verified). See `docs/assessments.md`.

- **Architecture**: Single Engineer ReAct agent (`PIPELINE_MODE=engineer`)
- **Orchestration**: LangGraph (StateGraph, single node → END)
- **Tool access**: MCP client (read-only enforcement), 6 meta-tools
- **Persistence**: PostgreSQL (state, audit, checkpoints) + Qdrant (vector KB, tool catalog, evidence)
- **LLM layer**: OpenAI-compatible models via `src/core/llm.py` (`LLMFactory`)
- **Frontend**: React dashboard (`frontend/`)

## Key Directories

```
src/
  agents/
    engineer.py           # ReAct agent LangGraph node
    engineer_prompts.py   # System prompt + embedded base skill
    engineer_tools.py     # 6 meta-tools factory (query_client_db, load_domain_skill, search_tool_catalog, search_knowledge_base, execute_tool, submit_findings)
    skills/               # Investigation methodology skills (base, networking, tool_catalog, etc.)
  assessments/    # Device Assessment module (definitions YAML, collector, evaluation, scoring, reporting, runner)
  core/           # Models, interfaces, audit, context/evidence stores, LLM factory, mcp_executor (shared MCP call helper)
  api/            # Platform API (FastAPI) — serves frontend + programmatic clients
  ingestion/      # Webhook ingestion + background execution service
  mcp/            # MCP client wrapper
  capabilities/   # Capability packs (generic/, future vendor-specific packs)
  utils/          # Logging, helpers
frontend/         # React dashboard (Vite + TypeScript)
mcp_gateway/      # Generic OpenAPI→MCP gateway service (own uv project + Dockerfile)
  gateway/        # Vendor-agnostic engine (spec pipeline, routing client, inventory)
  vendors/        # Appliance packs: vendors/<vendor>/<appliance>/ (fortinet/fortigate: manifest + 62 FortiOS specs + hooks)
  inventory/      # Device inventory per customer_id (gitignored; Fernet-encrypted tokens)
docs/
  agents/         # Engineer agent documentation
  architecture/   # Architecture design documents
  setup/          # Quickstart, configuration, deployment guides
  integrations/   # API reference, MCP tools, webhooks
  planning/       # Design specs (skills, data layer, model governance)
  legacy/         # Old 13-agent pipeline documentation (archived)
data/             # Runtime artifacts (gitignored)
```

## Engineer Agent

The Engineer agent replaces the previous 13-agent supervisor pipeline with a single ReAct reasoning loop.

**Meta-Tools:**

| Tool | Purpose |
|---|---|
| `query_client_db` | Load tenant context (devices, topology, baselines, recent changes) |
| `load_domain_skill` | Load domain-specific investigation methodology on-demand |
| `search_tool_catalog` | Semantic search over the indexed MCP tool catalog (2220 safety-filtered of 2776 gateway-exposed) |
| `search_knowledge_base` | Search vendor docs, runbooks, known issues |
| `execute_tool` | Execute MCP tools against live devices (read-only, direct — no AdaptiveExecutor) |
| `submit_findings` | Submit structured output (summary, hypotheses, facts, plan, case_status) |

**Mandatory sequence:** `query_client_db → load_domain_skill → search_tool_catalog → execute_tool (1+) → submit_findings`

**Skills system:** Base skill (`base_investigation.md`, "Logical Investigation Method" — causal process steps + attribution/exoneration rules + metacognitive Pre-Closure Check) always embedded in system prompt; the Output Contract lives in `engineer_prompts.py`, not in the skill. Domain skills loaded on-demand via `load_domain_skill`. 64 keyword mappings in `DOMAIN_SKILL_MAP`; domain skill files: `networking.md`, `tool_catalog.md`, `fortigate_licensing.md`, `fortigate_logs.md`, `flow_verification.md`, `lateral_thinking.md`. Authoring guide/template: `docs/agents/skill_authoring.md`.

## Current Implementation State

Check the active branch with `git branch --show-current`.

Completed:
- Single Engineer ReAct agent replacing 13-agent pipeline (legacy gated behind `PIPELINE_MODE=pipeline`; note `main.py test` and `run_mock.py` still run the legacy graph unconditionally — only the API path exercises the Engineer)
- Skills system (Pattern 1: pre-fetch base, Pattern 3: on-demand domain skills)
- Langfuse v4 observability fix (import, API, callback propagation)
- AdaptiveExecutor bypass in engineer mode (direct tool execution)
- submit_findings tool (structured output within reasoning chain, no post-hoc extraction)
- **MCP Gateway merge**: former `fortinet_ai_suite` repo absorbed as `mcp_gateway/` — generic OpenAPI→MCP gateway, appliance packs at `vendors/<vendor>/<appliance>/` (fortinet/fortigate: 62 FortiOS specs; fortinet/fortiedr: 26 generated OpenAPI 3 specs). Gateway exposes 2776 tools; the registry safety-filters to 2220 indexed in Qdrant `tool_catalog`. Tool names are frozen (fastmcp pinned + `baseline_tools.txt` + name-freeze test)
- **Multi-tenant gateway routing**: the gateway routes `(tenant, device)` per request via injected `tenant`/`device` header params (name-freeze safe). `tenant` is framework-injected by the app from the run `customer_id` (`engineer_tools.py:execute_tool`), never LLM-supplied; `TenantRegistries` (gateway `config.py`) lazily builds a per-tenant `DeviceRegistry`. No `ACTIVE_CUSTOMER_ID` — replaced by optional `DEFAULT_TENANT` fallback. Many tenants routable concurrently in one process
- Documentation overhaul (ops runbooks in `docs/operations/`, components guide, legacy docs archived)
- **Inventory sync app↔gateway**: gateway admin REST API (`/admin/*`, `X-Admin-Token`/`GATEWAY_ADMIN_TOKEN`, writes `devices/managed.yaml`, hot reload via `DeviceRegistry.reload()`); `InventoryService` propagates Component CRUD with `mcp_connection` via `gateway_admin_client.py` (token write-only, never persisted app-side; sync status in `Component.metadata["mcp"]`); frontend "MCP managed device" toggle in `ComponentModal`
- **Device Assessment module** (`src/assessments/`, branch feature/device-assessment): versioned YAML definitions → immutable DB snapshots (hash-guarded); deterministic CollectionEngine over `src/core/mcp_executor.py::execute_mcp_tool` (extracted from engineer_tools; strict read-only allowlist); evaluation rules→parsers→LLM (hybrid, citation-validated, injection-fenced); coverage-aware scoring; report model; state machine draft→queued→collecting→evaluating→completed|completed_with_errors|failed|cancelled; 12 API endpoints + `assessments:read/write` permissions (migration `e6f7a8b9c0d1`); frontend section (list/wizard/progress/results, first polling usage). Docs: `docs/assessments.md`

## Design Principles

- **Configuration-First**: Verify via existing configuration (routes, policies, rules, definitions) before live traffic. Never suggest sniffers, debug flows, or packet captures.
- **Domain-Agnostic**: All prompts are technology-neutral. No bias toward networking, infrastructure, or any specific IT domain.
- **Evidence-Only**: Never invent data. All conclusions must be backed by tool output.
- **Tenant Isolation**: All DB queries and Qdrant searches filter by `customer_id`. Evidence namespaced by tenant.

## Communication Rules

- Strict, professional, direct, technical tone.
- No enthusiastic language, colloquialisms, or filler phrases.
- No emojis or unnecessary exclamation marks.
- Concise: facts, code, explanations only.

## Operational Rules

- NEVER interact with Git (add/commit/push) unless explicitly instructed by the user.
- Read-Only enforcement: all MCP tools must be non-mutating; mutating tools are blocked by the safety keyword filter at registration and execution. (HITL approval for write actions is planned, not implemented.)
- Tenant isolation is mandatory: all DB queries and Qdrant searches must filter by `customer_id`.

## Important Files

| File | Purpose |
|---|---|
| `src/agents/engineer.py` | Engineer ReAct agent node |
| `src/agents/engineer_prompts.py` | System prompt with embedded base skill |
| `src/agents/engineer_tools.py` | 6 meta-tools factory + EngineerToolState |
| `src/agents/skills/` | Investigation methodology skills |
| `src/agent_graph_v2.py` | LangGraph graph (Engineer → END) |
| `src/core/models.py` | `Ticket`, `ClientContext`, `GlobalState`, `Hypothesis`, `Fact`, `Plan`, `CaseStatus`, etc. |
| `src/core/mcp_executor.py` | Shared MCP call helper (safety → governance → tenant injection → execution → error classification; `enforce_read_only` allowlist) |
| `src/assessments/runner.py` | Assessment state machine + background job entry point |
| `src/assessments/definitions/` | Versioned assessment definitions (YAML, immutable per version) |
| `src/core/llm.py` | `LLMFactory` |
| `src/core/evidence_store.py` | Content-addressable evidence (disk + Qdrant + PostgreSQL) |
| `src/core/langfuse_integration.py` | Langfuse v2/v4 observability |
| `src/core/orm.py` | SQLAlchemy ORM (TenantMixin with FK, cascade deletes) |
| `src/config.py` | Pydantic Settings, engineer config, MCP server config, safety keywords |
| `src/api/app.py` | Platform API (FastAPI) |
| `src/ingestion/service.py` | Ingestion + background execution service |
| `mcp_gateway/gateway/spec_pipeline.py` | OpenAPI→MCP build pipeline (tool-name freeze contract) |
| `mcp_gateway/vendors/fortinet/fortigate/manifest.yaml` | FortiGate appliance pack definition |
| `docs/architecture/mcp_gateway.md` | MCP Gateway architecture + vendor pack contract |
| `scripts/deploy/redeploy.sh` | Production redeploy (backup → build → name-freeze gate → deploy → rollback); runbook in `docs/operations/production_redeploy.md` |
| `docs/README.md` | Master documentation index |
