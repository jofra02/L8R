# Support AI Agent Framework

A production-grade, single-agent system that automates **L1/L2 technical support** for IT infrastructure, cloud, and application environments. Built on a **ReAct reasoning loop** powered by a single Engineer agent with domain-specific skills injection, **MCP (Model Context Protocol)** for secure read-only tool execution, and strict **multi-tenant** data isolation.

**[Full Documentation](docs/README.md)** | **[Quickstart](docs/setup/quickstart.md)** | **[API Reference](docs/integrations/api_reference.md)**

---

## Architecture

```
Webhook/API --> FastAPI --> Engineer ReAct Agent --> [6 meta-tools] --> Report
                                    |
                    +---------------+---------------+
                    |               |               |
              PostgreSQL        Qdrant        MCP Servers
                    |               |               |
                    +-------Evidence Store----------+
```

The system uses a single **Engineer ReAct agent** that reasons through IT support tickets in one continuous chain of thought. The agent has access to 6 meta-tools that provide structured access to client data, domain skills, tool catalogs, knowledge bases, external tool execution, and structured output submission.

### Engineer Meta-Tools

| Tool | Purpose |
|:---|:---|
| `query_client_db` | Retrieve tenant context, topology, configuration from PostgreSQL |
| `load_domain_skill` | Inject domain-specific investigation methodology into the agent's context |
| `search_tool_catalog` | Semantic search across 2182 indexed MCP tool descriptions |
| `search_knowledge_base` | Query Qdrant for runbooks, KB articles, past resolutions |
| `execute_tool` | Run a read-only MCP tool against an external system |
| `submit_findings` | Emit structured diagnosis, remediation plan, and report |

### Skills System

The Engineer agent operates with a **base investigation methodology** always present in its system prompt, covering general diagnostic reasoning, evidence gathering, and structured reporting. **Domain-specific skills** (networking, cloud, database, security, etc.) are loaded on-demand via the `load_domain_skill` tool when the agent determines specialized methodology is needed.

### LangGraph

LangGraph is still used for orchestration, but the graph is minimal:

```
Engineer Node --> END
```

Defined in `src/agent_graph_v2.py`. The Engineer node runs the full ReAct loop internally.

---

## Key Features

- **Single ReAct Reasoning Loop.** One LLM, one chain of thought. No inter-agent coordination overhead. The Engineer reasons, gathers evidence, and produces a structured report in a single pass.
- **Skills System.** Domain-specific investigation methodologies injected on-demand. Base methodology always loaded. Extensible to any IT domain.
- **Semantic Tool Catalog Search.** 2182 MCP tools indexed by description in Qdrant. The agent searches for relevant tools by intent rather than memorizing tool names.
- **Content-Addressable Evidence Store.** Immutable evidence snapshots stored on disk, indexed in Qdrant, tracked in PostgreSQL. Deduplicated by content hash.
- **Multi-Tenant Isolation.** All database queries, Qdrant searches, and evidence storage are scoped by `customer_id`. No cross-tenant data leakage.
- **Read-Only Tool Governance.** The agent can query, get, and list but never modify external systems. Write actions require human-in-the-loop approval via LangGraph interrupt.
- **Langfuse Observability.** Full trace visibility into the ReAct loop, tool calls, and LLM interactions. Compatible with Langfuse v4.
- **React Frontend Dashboard.** Web-based UI at `frontend/` for ticket submission, run monitoring, and report viewing.
- **Structured Engineering Reports.** Output is a formatted technical document with diagnosis, remediation steps, validation procedures, and rollback plans.

---

## Data Layer

### PostgreSQL (Relational)

Stores tenant configuration, ticket state, run metadata, audit logs, and evidence references. All tables enforce `customer_id` foreign key constraints with cascade deletes. See [Data Layer Reference](docs/architecture/data_layer.md).

### Qdrant (Vector)

Collections with mandatory `customer_id` isolation:

| Collection | Purpose |
|:---|:---|
| `knowledge_base` | KB chunks (runbooks, docs) |
| `evidence` | Tool output snapshots |
| `tool_catalog` | MCP tool descriptions for semantic search |
| `resolved_tickets` | Past cases for contextual learning |

### Evidence Store

Content-addressable, immutable snapshots. Each piece of evidence is hashed and stored on disk, indexed in Qdrant for semantic retrieval, and tracked in PostgreSQL for relational queries. Namespaced by `customer_id`.

### MCP (Tool Execution)

Tools are served by external MCP servers (stdio or SSE transport). The system indexes tool descriptions at startup for semantic catalog search. See [MCP Integration Guide](docs/integrations/mcp_tools.md).

---

## Getting Started

See [docs/setup/quickstart.md](docs/setup/quickstart.md) for the full guide.

### Prerequisites

- **Python 3.12+**
- **Docker** (PostgreSQL + Qdrant)
- **uv** (package manager)
- **Node.js 20+** (frontend)

### 1. Install

```bash
git clone <repo-url>
cd support_ai_agent
uv sync
```

### 2. Configure

Create `.env` in the project root:

```ini
PIPELINE_MODE=engineer

# LLM
OPENAI_API_KEY=sk-...
LLM_MODEL_ENGINEER=gpt-5.4

# Engineer limits
ENGINEER_MAX_TOOL_CALLS=30
ENGINEER_MAX_ITERATIONS=50
ENGINEER_TIMEOUT_SECONDS=600

# PostgreSQL
DB_HOST=127.0.0.1
DB_PORT=5432
DB_USER=postgres
DB_PASS=change_me
DB_NAME=support_agent_db

# Qdrant
QDRANT_URL=http://127.0.0.1:6333
```

See `src/config.py` for all configuration options.

### 3. Initialize

```bash
# PostgreSQL schema
uv run alembic upgrade head

# Qdrant collections + indexes
uv run python -m src.utils.init_qdrant
```

### 4. Run

```bash
uvicorn src.api.app:app --reload --port 8000
```

---

## Project Layout

```
src/
├── agents/
│   ├── engineer.py          # ReAct agent node
│   ├── engineer_prompts.py  # System prompt + base skill
│   ├── engineer_tools.py    # 6 meta-tools factory
│   └── skills/              # Investigation methodology skills
├── core/                    # Models, LLM, audit, evidence, safety
├── api/                     # Platform API (FastAPI)
├── ingestion/               # Webhook ingestion
├── mcp/                     # MCP client
└── plugins/                 # Capability packs
frontend/                    # React dashboard
docs/
├── setup/                   # Quickstart, configuration, deployment
├── architecture/            # Overview, data layer, observability, safety
├── agents/                  # Agent documentation
├── integrations/            # API reference, MCP tools, webhooks
└── legacy/                  # Old 13-agent pipeline docs
```

---

## Configuration

| Variable | Default | Description |
|:---|:---|:---|
| `PIPELINE_MODE` | `engineer` | `engineer` (single agent) or `pipeline` (legacy 13-agent) |
| `LLM_MODEL_ENGINEER` | `gpt-5.4` | Model for the Engineer ReAct agent |
| `ENGINEER_MAX_TOOL_CALLS` | `30` | Maximum tool executions per run |
| `ENGINEER_MAX_ITERATIONS` | `50` | Maximum ReAct loop iterations |
| `ENGINEER_TIMEOUT_SECONDS` | `600` | Hard timeout for a single run |

---

## Documentation Index

### Core

| Topic | Doc |
|:---|:---|
| Engineer Agent | [docs/agents/engineer.md](docs/agents/engineer.md) |

### Architecture and Design

| Topic | Doc |
|:---|:---|
| Architecture Overview | [docs/architecture/](docs/architecture/) |
| Data Layer Reference | [docs/architecture/data_layer.md](docs/architecture/data_layer.md) |
| Observability | [docs/architecture/observability.md](docs/architecture/observability.md) |
| Safety and Governance | [docs/architecture/safety_and_governance.md](docs/architecture/safety_and_governance.md) |

### Setup

| Topic | Doc |
|:---|:---|
| Quickstart | [docs/setup/quickstart.md](docs/setup/quickstart.md) |
| Configuration | [docs/setup/configuration.md](docs/setup/configuration.md) |
| Deployment | [docs/setup/deployment.md](docs/setup/deployment.md) |

### Integration

| Topic | Doc |
|:---|:---|
| API Reference | [docs/integrations/api_reference.md](docs/integrations/api_reference.md) |
| MCP Tools | [docs/integrations/mcp_tools.md](docs/integrations/mcp_tools.md) |
| Webhooks | [docs/integrations/webhooks.md](docs/integrations/webhooks.md) |

### Legacy

| Topic | Doc |
|:---|:---|
| Old 13-Agent Pipeline | [docs/legacy/](docs/legacy/) |
