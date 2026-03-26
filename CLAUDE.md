# CLAUDE.md — support_ai_agent

## Project Overview

Single-agent L1/L2 technical support framework. Receives IT support tickets (incidents/changes), runs a single Engineer ReAct agent that autonomously investigates using 6 meta-tools, then produces structured findings — without executing any write actions on external systems. Domain-agnostic: works across networking, infrastructure, cloud, application, database, security, and any IT domain.

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
  core/           # Models, interfaces, audit, context/evidence stores, LLM factory
  api/            # Platform API (FastAPI) — serves frontend + programmatic clients
  ingestion/      # Webhook ingestion + background execution service
  mcp/            # MCP client wrapper
  plugins/        # Capability packs (generic/, future vendor-specific packs)
  utils/          # Logging, helpers
frontend/         # React dashboard (Vite + TypeScript)
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
| `search_tool_catalog` | Semantic search over 2000+ indexed MCP tools |
| `search_knowledge_base` | Search vendor docs, runbooks, known issues |
| `execute_tool` | Execute MCP tools against live devices (read-only, direct — no AdaptiveExecutor) |
| `submit_findings` | Submit structured output (summary, hypotheses, facts, plan, case_status) |

**Mandatory sequence:** `query_client_db → load_domain_skill → search_tool_catalog → execute_tool (1+) → submit_findings`

**Skills system:** Base investigation methodology always embedded in system prompt. Domain skills (networking, firewall, vpn, etc.) loaded on-demand via `load_domain_skill`. 42 keyword mappings in `DOMAIN_SKILL_MAP`.

## Current Implementation State

**Active branch:** `0.3.0-agent_refactor_plus_skills`

Completed this cycle:
- Single Engineer ReAct agent replacing 13-agent pipeline
- Skills system (Pattern 1: pre-fetch base, Pattern 3: on-demand domain skills)
- Langfuse v4 observability fix (import, API, callback propagation)
- AdaptiveExecutor bypass in engineer mode (direct tool execution)
- submit_findings tool (structured output within reasoning chain, no post-hoc extraction)
- Semantic tool catalog search guidance in system prompt
- Evidence store ON CONFLICT DO NOTHING fix for re-runs
- Documentation overhaul (legacy docs archived)

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
- Read-Only enforcement: all MCP tools must be non-mutating. All write actions require HITL approval via LangGraph interrupt.
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
| `src/core/llm.py` | `LLMFactory` |
| `src/core/evidence_store.py` | Content-addressable evidence (disk + Qdrant + PostgreSQL) |
| `src/core/langfuse_integration.py` | Langfuse v2/v4 observability |
| `src/core/orm.py` | SQLAlchemy ORM (TenantMixin with FK, cascade deletes) |
| `src/config.py` | Pydantic Settings, engineer config, MCP server config, safety keywords |
| `src/api/app.py` | Platform API (FastAPI) |
| `src/ingestion/service.py` | Ingestion + background execution service |
| `docs/README.md` | Master documentation index |
