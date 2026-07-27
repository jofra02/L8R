# Architecture Overview

> System-level design of the single-agent L1/L2 technical support framework. For how each component works in detail, see the [Components Guide](components.md).

## Overview

The system receives IT support tickets (incidents, changes, requests) via webhooks, REST API, or the React dashboard. A single Engineer ReAct agent processes each ticket through an autonomous reasoning loop, using six meta-tools to gather context, load domain methodology, discover and execute tools, and produce a structured resolution report. No write actions are executed on external systems without human approval.

A second product module, **Device Assessments** (`src/assessments/`), runs deterministic, definition-driven security assessments over managed devices. Versioned YAML definitions pin the collection steps and controls; the LLM never chooses tools — it only assists `hybrid`/`llm` controls over pre-collected evidence. See [Device Assessments](../assessments.md).

Outbound **notifications** (`src/notifications/`) push `ticket.ingested` and `run.completed` events to a global n8n webhook, with every delivery persisted for manual resend. See [Notifications](../notifications.md).

The architecture follows three core principles:
- **Configuration-First**: Verify via existing configuration before live traffic analysis
- **Evidence-Only**: All conclusions must be backed by tool output
- **Tenant Isolation**: All data queries filter by `customer_id`

## System Diagram

```mermaid
graph TD
    subgraph "Ingestion Layer"
        WH["Webhook / REST API"] -->|"HTTP 202"| API["FastAPI"]
        UI["React Dashboard"] --> API
    end

    API -->|"Normalized Ticket"| CORE
    API -->|"Assessment job"| ASMT
    API -->|"ticket.ingested / run.completed"| N8N["n8n Webhook (notifications)"]

    subgraph CORE["Agentic Core"]
        ENG["Engineer ReAct Agent"]
        ENG -->|invoke| MT1["query_client_db"]
        ENG -->|invoke| MT2["load_domain_skill"]
        ENG -->|invoke| MT3["search_tool_catalog"]
        ENG -->|invoke| MT4["search_knowledge_base"]
        ENG -->|invoke| MT5["execute_tool"]
        ENG -->|invoke| MT6["submit_findings"]
        ASMT["Assessment Runner (deterministic)"]
    end

    subgraph DATA["Data Layer"]
        PG[("PostgreSQL")]
        QD[("Qdrant")]
        MCP_S["MCP Gateway / MCP Servers"]
        FS["Evidence Store (disk)"]
    end

    CORE -->|"state, audit"| PG
    CORE -->|"KB, evidence, tools, CBR"| QD
    CORE -->|"read-only tools"| MCP_S
    CORE -->|"evidence snapshots"| FS

    subgraph OBS["Observability"]
        LF["Langfuse v4"]
    end

    CORE -->|"traces, spans"| LF
```

## Components

### Ingestion Layer
- **FastAPI server** (`src/api/app.py`): Receives tickets via webhook (HTTP 202 async pattern). Returns `ticket_id` + `run_id` for polling.
- **React frontend** (`frontend/`): Dashboard for ticket submission, run monitoring, and report viewing.
- **Normalizers**: Convert source-specific payloads into the standard `Ticket` model.

### Agentic Core
- **LangGraph StateGraph** (`src/agent_graph_v2.py`): Single-node graph containing the Engineer agent. Built using `langgraph.prebuilt.create_react_agent` for autonomous ReAct reasoning.
- **Engineer ReAct Agent**: Operates in a think-act-observe loop. Six meta-tools provide structured access to all system capabilities:
  - `query_client_db` -- retrieve tenant context, topology, and configuration
  - `load_domain_skill` -- load domain-specific methodology (investigation steps, key questions, common patterns)
  - `search_tool_catalog` -- semantic search over available MCP tools, scoped to the appliance-pack versions matching the tenant's managed devices (`src/core/pack_matching.py`)
  - `search_knowledge_base` -- search KB articles, resolved tickets, and evidence
  - `execute_tool` -- invoke an MCP tool with parameters via the shared `src/core/mcp_executor.py` (safety, governance, tenant injection, read-only enforcement)
  - `submit_findings` -- finalize the structured report (summary, hypotheses, facts, plan, case_status)
- **Skills system**: Domain-specific methodology files loaded on demand. Each skill provides investigation guidance, key questions, and common failure patterns for a given domain.
- **Assessment Runner** (`src/assessments/runner.py`): Deterministic state machine (draft → queued → collecting → evaluating → completed) that executes versioned assessment definitions against managed devices. Shares the read-only MCP execution path (`src/core/mcp_executor.py`) but never lets the LLM choose tools.

### Data Layer
- **PostgreSQL**: Relational state (tickets, runs, audit logs, tenant config, RBAC, assessment runs, notification deliveries). All tables enforce `customer_id` FK constraints with cascade deletes.
- **Qdrant**: 6 vector collections:
  - `knowledge_base` -- KB articles and documentation
  - `evidence` -- evidence snapshots from tool executions
  - `tool_catalog` -- MCP tool descriptions for semantic discovery, logically partitioned by appliance-pack identity (`pack_vendor`/`pack_product`/`pack_version`/`pack_key`)
  - `tool_knowledge` -- learned tool usage patterns (legacy pipeline)
  - `resolved_tickets` -- past resolutions for case-based reasoning
  - `adaptive_fixes` -- self-healing parameter corrections (legacy pipeline)
  - All queries filter by `customer_id`.
- **Evidence Store**: Content-addressable disk storage for immutable evidence snapshots. Namespaced by tenant.
- **MCP Gateway / MCP Servers**: External tool providers (stdio or SSE transport). The bundled [MCP Gateway](mcp_gateway.md) is the primary server; all are auto-discovered at startup via `CapabilityRegistry`.

### Observability
- **Langfuse v4**: Trace and span integration for full pipeline visibility. Callbacks propagated to the react agent via `react_agent.ainvoke` config. Each tool invocation creates a child span.

## Tech Stack

| Component | Technology |
|---|---|
| Orchestration | LangGraph (StateGraph + `create_react_agent`) |
| API | FastAPI |
| LLM | OpenAI-compatible models via `LLMFactory` |
| Relational DB | PostgreSQL + SQLAlchemy (async) |
| Vector DB | Qdrant |
| Tool Protocol | MCP (Model Context Protocol) via FastMCP |
| Migrations | Alembic |
| Package Manager | uv |
| Observability | Langfuse v4 |
| Frontend | React |

## Data Flow

1. Ticket arrives via webhook or dashboard submission, normalized to `Ticket` model, HTTP 202 returned (a `ticket.ingested` notification fires if configured)
2. Background task creates a run and launches the Engineer ReAct agent with initial state
3. Engineer queries tenant context (`query_client_db`)
4. Engineer loads the appropriate domain skill (`load_domain_skill`)
5. Engineer searches for relevant tools (`search_tool_catalog`) and knowledge (`search_knowledge_base`)
6. Engineer executes tools to gather evidence (`execute_tool`), repeating as needed
7. Engineer submits structured findings (`submit_findings`) -- summary, hypotheses, facts, plan, case_status
8. Report stored in PostgreSQL; client polls for the result (a `run.completed` notification with the full findings fires if configured)

## See Also

- [Components Guide](components.md) - How each component works (medium depth)
- [Engineer Agent](../agents/engineer.md) - Meta-tools, skills system, reasoning loop
- [MCP Gateway](mcp_gateway.md) - The bundled OpenAPI→MCP tool server
- [Device Assessments](../assessments.md) - Deterministic definition-driven assessments
- [Notifications](../notifications.md) - Outbound n8n webhook egress
- [Data Layer](data_layer.md) - Schema and collections
- [Observability](observability.md) - Langfuse integration
- [Safety and Governance](safety_and_governance.md) - Tool safety model
- [Operations Manual](../operations/README.md) - Runbooks
