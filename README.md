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
| `search_tool_catalog` | Semantic search across the indexed MCP tool catalog (2220 safety-filtered tools of the 2776 the gateway exposes) |
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
- **Semantic Tool Catalog Search.** The MCP Gateway exposes 2776 tools; the registry safety-filters them to 2220, indexed by description in Qdrant. The agent searches for relevant tools by intent rather than memorizing tool names.
- **Content-Addressable Evidence Store.** Immutable evidence snapshots stored on disk, indexed in Qdrant, tracked in PostgreSQL. Deduplicated by content hash.
- **Multi-Tenant Isolation.** All database queries, Qdrant searches, and evidence storage are scoped by `customer_id`. No cross-tenant data leakage.
- **Read-Only Tool Governance.** The agent can query, get, and list but never modify external systems: mutating tools are blocked by a keyword safety filter at both registration and execution time. (Human-in-the-loop approval for write actions is planned, not yet implemented.)
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
| `tool_knowledge` | Per-tool usage knowledge (legacy pipeline) |
| `adaptive_fixes` | Learned tool-call fixes (legacy pipeline) |

### Evidence Store

Content-addressable, immutable snapshots. Each piece of evidence is hashed and stored on disk, indexed in Qdrant for semantic retrieval, and tracked in PostgreSQL for relational queries. Namespaced by `customer_id`.

### MCP (Tool Execution)

Tools are served by MCP servers (stdio or SSE transport). The platform bundles its own: the **MCP Gateway** (`mcp_gateway/`), a generic OpenAPI→MCP service whose appliance packs (62 FortiOS specs, 26 FortiEDR specs) convert into 2776 tools; the agent's registry safety-filters these to 2220 registered and indexed for semantic catalog search at startup. See [MCP Integration Guide](docs/integrations/mcp_tools.md) and [MCP Gateway](docs/architecture/mcp_gateway.md).

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

Copy `.env.example` to `.env` and set at minimum `OPENAI_API_KEY` and the PostgreSQL/Qdrant connection values. Full reference: [docs/setup/configuration.md](docs/setup/configuration.md).

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
└── capabilities/            # Capability packs
frontend/                    # React dashboard
mcp_gateway/                 # Generic OpenAPI→MCP gateway service (tool execution)
├── gateway/                 # Vendor-agnostic engine
├── vendors/                 # Appliance packs: vendors/<vendor>/<appliance>/<version>/
│   └── fortinet/fortigate/  # FortiGate pack (manifest + FortiOS specs + hooks)
└── inventory/               # Per-tenant device inventory (gitignored, encrypted tokens)
docs/
├── setup/                   # Quickstart, configuration, deployment
├── operations/              # Runbooks (ops manual)
├── architecture/            # Overview, components, data layer, observability, safety
├── agents/                  # Agent documentation
├── integrations/            # API reference, MCP tools, webhooks
└── legacy/                  # Old 13-agent pipeline docs
```

---

## Configuration

| Variable | Default | Description |
|:---|:---|:---|
| `PIPELINE_MODE` | `engineer` | `engineer` (current single agent); `pipeline` is a deprecated legacy toggle |
| `LLM_MODEL_ENGINEER` | `gpt-5.4` | Model for the Engineer ReAct agent |
| `ENGINEER_MAX_TOOL_CALLS` | `30` | Maximum tool executions per run |
| `ENGINEER_MAX_ITERATIONS` | `50` | Maximum ReAct loop iterations |
| `ENGINEER_TIMEOUT_SECONDS` | `600` | Hard timeout for a single run |

---

## Documentation

| Topic | Doc |
|:---|:---|
| Quickstart | [docs/setup/quickstart.md](docs/setup/quickstart.md) |
| Operations Manual (runbooks) | [docs/operations/README.md](docs/operations/README.md) |
| Components Guide | [docs/architecture/components.md](docs/architecture/components.md) |
| Architecture Overview | [docs/architecture/overview.md](docs/architecture/overview.md) |
| API Reference | [docs/integrations/api_reference.md](docs/integrations/api_reference.md) |
| **Full index** | [docs/README.md](docs/README.md) |
