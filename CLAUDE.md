# CLAUDE.md — support_ai_agent

## Project Overview

Multi-agent L1/L2 technical support framework. Receives IT support tickets (incidents/changes), orchestrates a LangGraph pipeline of specialized agents to diagnose, enrich, hypothesize, and generate resolution plans — without executing any write actions on external systems. Domain-agnostic: works across networking, infrastructure, cloud, application, database, security, and any IT domain.

- **Orchestration**: LangGraph (stateful, checkpointed)
- **Tool access**: MCP client (read-only enforcement)
- **Persistence**: PostgreSQL (state, audit, checkpoints) + Qdrant (vector KB)
- **LLM layer**: OpenAI-compatible models via `src/core/llm.py` (`LLMFactory`)

## Key Directories

```
src/
  agents/         # LangGraph nodes (supervisor, classifier, evidence_collector, etc.)
  core/           # Models, interfaces, audit, context/evidence stores, LLM factory
  ingestion/      # Webhook API (FastAPI) + REST/MCP pollers
  mcp/            # MCP client wrapper
  plugins/        # Capability packs (generic/, future vendor-specific packs)
  utils/          # Logging, helpers
docs/
  agents/         # Per-agent documentation
  architecture/   # Architecture design documents (adaptive execution, data layer, etc.)
  planning/       # Implementation plan + framework spec
data/             # Runtime artifacts (gitignored): paused_state.json, needs.json
```

## Agent Pipeline

| Agent | Key Output |
|---|---|
| ContextAgent | `client_context`, seeded `topology_nodes/edges` |
| Classifier | `classification` (domains, confidence) |
| Mapper | `components` (with vendor, reconciled against inventory) |
| EvidenceCollector | `evidence_refs` (via keyword intent -> semantic tool search) |
| Enricher | `facts`, `structured_facts` (with provenance), `topology_nodes/edges` |
| HypothesisAgent | `hypotheses` (ranked, with `evidence_refs`), `path_analysis` |
| InvestigationPlanner | `open_questions` (structured question-driven investigation) |
| GoalDecomposer | `fulfillment_goals` (change/request ticket decomposition) |
| Scoring | `scoring` (deterministic decision gate + stagnation detection, no LLM) |
| Investigator | `evidence_refs` (targeted, consumes `open_questions`) |
| ResolutionPlanner | `plan` (diagnosis, remediation, validation, rollback) |
| Response | `final_answer`, `handoff` |

## Current Implementation State

**Phases 1–18 complete.** Active work: **beta-0.0.8** (spec alignment, structured investigation, case lifecycle).

Completed this cycle:
- Tenant isolation audit & remediation (all runtime + schema findings)
- Alembic migrations for FK constraints, cascade deletes, compound indexes
- Mapper inventory reconciliation (deterministic post-processing)
- Evidence collector intent system rewrite (keyword queries for semantic search)
- Domain bias audit & remediation across all agent prompts
- Configuration-first principle (prefer config analysis over live traffic)
- Safety keywords expansion (database, deployment, permission operations)
- InvestigationPlanner agent (structured OpenQuestion-driven investigation)
- GoalDecomposer agent (fulfillment path for change/request tickets)
- CaseStatus lifecycle tracking across all agents
- Structured Fact model with provenance (source_evidence_id, confidence)
- Evidence-to-Hypothesis linking (evidence_refs on Hypothesis)
- Stagnation detection in Scoring agent
- Planner renamed to ResolutionPlanner (post-diagnosis)

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
| `src/core/models.py` | `Ticket`, `ClientContext`, `GlobalState`, `Hypothesis`, `OpenQuestion`, `Fact`, `FulfillmentGoal`, `CaseStatus`, `TopologyNode/Edge`, etc. |
| `src/core/interfaces.py` | `PluginInterface`, `MCPToolInterface`, `IngestorInterface` |
| `src/core/audit.py` | `AuditService` (tenant-aware) |
| `src/core/llm.py` | `LLMFactory` |
| `src/core/adaptive_executor.py` | Self-healing tool execution with learning |
| `src/core/orm.py` | SQLAlchemy ORM (TenantMixin with FK, cascade deletes) |
| `src/agent_graph.py` | LangGraph workflow + edges |
| `src/config.py` | Pydantic Settings, LLM profiles, MCP server config, safety keywords |
| `src/ingestion/api.py` | FastAPI webhook endpoint |
| `src/ingestion/service.py` | Ingestion service logic |
| `docs/agents/` | Per-agent documentation |
| `docs/architecture/` | Architecture design documents |
| `docs/planning/multiagent_framework_v2.md` | Detailed framework spec (architecture bible) |
