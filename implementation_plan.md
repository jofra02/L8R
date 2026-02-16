# Implementation Plan - Multi-Agent L1/L2 Tech Framework

This plan outlines the development of a modular, vendor-agnostic, multi-agent system for handling technical tickets (Incidents and Changes). The system uses LangGraph for orchestration and MCP for read-only tool interactions.

## User Review Required

> [!IMPORTANT]
> **Read-Only Enforcement**: The system relies on strict discipline in tool implementation. All MCP tools must be verified as non-mutating.

> [!NOTE]
> **Persistence**: For MVP, we will use in-memory state or simple file-based checkpoints. Real production use would require a proper database (PostgreSQL/Redis).

## Proposed Architecture

The project will follow a strict modular structure to separate core logic from vendor-specific plugins.

### Directory Structure

```text
/src
  /core
    /models       # Pydantic models for State, Ticket, Context, etc.
    /interfaces   # Abstract base classes for Plugins, Tools, Normalizers
    /engine       # Logic for Playbooks and Hypotheses independent of LangGraph
  /agents         # LangGraph nodes (Supervisor, Classifier, etc.)
  /mcp            # MCP Server & Tool wrappers
  /plugins        # Vendor implementations
    /generic      # Standard/Common implementations
    /cisco        # (Future)
    /fortinet     # (Future)
  /utils          # Logging, Security, Common helpers
```

## Proposed Changes

### Input Layer (Ingestion Strategy)

All inputs must be normalized into a standard `Ticket` object before entering the LangGraph.

- **Webhook Receiver (Push)**: FastAPI endpoint `/api/v1/webhook/{source}` to accept JSON payloads (e.g., from ServiceNow, Jira, AlertManager).
- **REST Poller (Pull)**: Scheduled task (APScheduler) that queries external APIs (e.g., `GET /incidents?since=...`) and dedupes against DB.
- **MCP Tool Poller (Pull)**: Agentic loop that calls `read_alerts()` on a connected MCP server.

### Capability Registry (was "Plugins")

The system uses a **Capability Registry** to manage vendor-agnostic extensions ("Capability Packs").
A **Capability Pack** includes:
- **MCP Tools** (Adapters)
- **Normalizers** (Raw -> Common Evidence Model)
- **Playbooks** (YAML)
- **Hypothesis Templates**

### Data Layer (Memory Hierarchy)

- **Short-term Memory**: LangGraph State (persisted via Postgres Checkpoints). Tracks the current ticket execution.
- **Long-term Memory**: `ClientContext` (Facts, Baselines, Topology) stored in Postgres/Qdrant. Versioned.
- **Evidence Store**: Immutable snapshots of raw tool outputs (JSON/Text) stored in Blob Storage/Postgres, referenced by `raw_refs` in State.
```python
class GlobalState(TypedDict):
    ticket: Ticket
    customer_id: str
    client_context: ClientContext
    classification: Classification
    components: List[Component]
    facts: Dict[str, Any]  # normalized evidence
    missing_info: List[str]
    hypotheses: List[Hypothesis]
    plan: Plan
    final_answer: str
    meta: Dict[str, Any]  # iterations, tool_calls, trace_id
```

#### Ticket
```python
class Ticket(BaseModel):
    id: str
    mode: Literal["incident", "change"]
    text: str
    severity: str
    timestamps: Dict[str, str]
```

### Database Layer (Data Isolation Strategy)

The system relies on external databases and connects via standard drivers. No infrastructure provisioning occurs within the agent ecosystem.

- **Relational: PostgreSQL**
    - Stores: `Tickets`, `Checkpoints` (LangGraph state persistence), `AuditLogs`.
    - **Isolation Strategy**: Row-Level Security (RLS) is ENFORCED. All queries MUST filter by `customer_id`.
    - **Responsibility**: Connect, validate schema versions, and apply migrations if needed (using Alembic/SQLModel).

- **Vector Store: Qdrant**
    - Stores: `KnowledgeBase` (documentation, past tickets, error codes).
    - **Isolation Strategy**: Payload-based filtering. Every vector search MUST include `filter={ "must": [ { "key": "customer_id", "match": { "value": CUSTOMER_ID } } ] }`.
    - **Responsibility**: Connect to collection, ensure config/index exists.

### Core Interfaces (`src/core/interfaces.py`)

- **PluginInterface**:
    - `get_tools()`: Returns list of MCP tools.
    - `get_playbooks()`: Returns list of playbook definitions.
    - `get_normalizers()`: Returns evidence normalizers.
    - `get_hypothesis_templates()`: Returns reasoning templates.

- **MCPToolInterface**:
    - `name`: str
    - `description`: str
    - `execute(args: Dict) -> str`: The actual read-only logic.

### Agent Logic (`src/agents/`)

Each agent will be a distinct module within the LangGraph, aligned with the **Triage Pipeline** pattern (Ingest -> Normalize -> Evidence -> Enrich -> Decide):

| Agent | Responsibility | Output Update in State |
| :--- | :--- | :--- |
| **Supervisor** | Router & orchestrator. Decides phase transitions and HITL interrupts. | `meta.iterations` |
| **ContextAgent** | Fetches `ClientContext`. Validates customer existence. | `client_context` |
| **Normalizer** | **[NEW]** Converts raw inputs/logs to **ECS/CIM** standard schema. | `facts.normalized` |
| **Classifier** | Determines ticket type (Incident/Change) and domains. | `classification`, `ticket.mode` |
| **Scoper/Mapper** | Identifies involved components (devices/services). | `components` |
| **EvidenceCollector** | Executes playbooks via MCP tools. | `facts`, `missing_info` |
| **Enricher** | **[NEW]** Maps findings to MITRE ATT&CK or known constraints. | `facts.enriched` |
| **HypothesisAgent** | Generates reasons for incidents or constraints for changes. | `hypotheses` (ranked) |
| **Planner** | Generates resolution plan without side effects. **Strict separation of Planner vs Executor.** | `plan` |
| **Response** | Formats final output for human consumption. | `final_answer` |

### Plugin System (FastMCP & Standards)

- **Tooling**: Use **FastMCP** `(fastmcp)` to rapidly expose Python functions as MCP tools.
    - **OpenAPI Integration**: Convert vendor APIs to MCP tools automatically where possible, but curating "safe" endpoints.
- **Normalization**: Plugins must map vendor-specific logs to **Elastic Common Schema (ECS)** or **Splunk CIM** to ensure cross-vendor correlation.

### Security & Governance (SOTA)

- **Policy Gates**: ALL "write" actions (even draft creations) require explicit **Human-in-the-Loop (HITL)** approval via LangGraph interrupts.
- **Immutable Evidence**: Evidence gathered must be hashed/stored to prevent tampering (Evidence Store pattern).
- **Prompt Injection Mitigation**: Treat retrieved content as *data*, not instructions. Use structured outputs (JSON) exclusively for critical decisions.

## Practical Roadmap & Phases (Implementation Order)

### Phase 1: Foundation & Domain Modeling
1.  Initialize Project (Poetry/UV, Git).
2.  Define Core Models (`Ticket`, `ClientContext`, `State`) in `src/core/models.py`.
3.  Set up Logging & Configuration (Environment variables).

### Phase 2: Data Layer (Persistence)
1.  Setup PostgreSQL (AsyncPG/SQLAlchemy) & Migrations (Alembic).
2.  Setup Qdrant Client (Vector Store).
3.  Implement Isolation Logic (Tenant filtering mixins).

### Phase 3: Input Layer (Getting Data In)
1.  Implement `IngestorInterface`.
2.  Create Webhook Endpoint (FastAPI).
3.  Create Poller (REST & MCP) mechanism.
4.  Implement Normalization Logic (Raw -> Ticket).

### Phase 4: Core Agent Framework (LangGraph)
1.  Implement MCP Client (Read-Only enforcement).
2.  Design Graph Topology (Supervisor -> Nodes).
3.  Implement Node Logic (Context, Evidence, Plan, etc.).
4.  Implement State Checkpointing (Postgres).

### Phase 5: Capability System (Registry & Packs)
1.  Implement **Capability Registry** loader.
2.  Create `generic` Capability Pack (Ping, DNS, HTTP check).
3.  Add `FastMCP` integration for Adapter generation.

### Phase 6: API & UI (Interaction)
1.  Expose API for Chat/Feedback.
2.  Implement HITL Approval Endpoints.
3.  (Optional) Simple Streamlit/NextJS Dashboard.

## Verification Plan

### Automated Tests
- Unit tests for Model validation and State transitions.
- Mock MCP server to test tool execution without real infrastructure.
- Test the "Stop Conditions" to ensure agents don't loop infinitely.

### Manual Verification
- Run a simulated logical flow for an "Incident" ticket.
- Verify the output format matches the requirements.
