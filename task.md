# Tasks

[x] Phase 1: Foundation & Domain Modeling
    [x] Initialize Project (uv, Git structure)
    [x] Define Core Models (`Ticket`, `ClientContext`, `State`) in `src/core/models.py`
    [x] Define Interfaces (`Ingestor`, `Plugin`, `MCPTool`) in `src/core/interfaces.py`
    [x] Setup Logging & Config (Env vars, Pydantic Settings)

[x] Phase 2: Data Layer (Persistence)
    [x] Database Integration (PostgreSQL)
        [x] Define ORM Models (SQLModel/SQLAlchemy) with Tenant Mixin
        [x] Setup Async Database Session Manager
        [x] Implement Alembic Migrations for initial schema
    [x] Knowledge Base Integration (Qdrant)
        [x] Setup Qdrant Async Client wrapper
        [x] Implement Collection Manager (ensure exists + config)
        [x] Implement Vector Store Interface with MANDATORY tenant filtering

[x] Phase 3: Input Layer (Getting Data In)
    [x] Implement `IngestorInterface` (fetch/normalize)
    [x] Implement Webhook Receiver (FastAPI endpoint)
    [x] Implement REST Poller (Periodic task)
    [x] Implement MCP Tool Poller (Agentic dynamic read)
    [x] Implement Normalizer Logic (Raw -> Standard Ticket)

[x] Phase 4: Core Agent Framework (LangGraph)
    [x] Implement Memory Hierarchy (Short-term State, Long-term Context)
    [x] Implement Context Agent
    [x] Implement Classifier Agent
    [x] Implement Scoper/Mapper Agent
    [x] Implement Supervisor Agent (Router & State Management)
    [x] Implement Normalizer Agent (ECS/CIM Mapper)
    [x] Implement Evidence Collector Agent
    [x] Implement Enricher Agent (MITRE/KB Mapping)
    [x] Implement Hypothesis Agent
    [x] Implement Planner Agent (Plan-and-Solve Pattern)
    [x] Implement Response Agent
    [x] Implement Policy Gates & HITL Interrupts

[x] Phase 5: Capability System (Registry & Packs)
    [x] Create `CapabilityRegistry` loader
    [x] Setup `FastMCP` framework (Deferred/Manual for MVP)
    [x] Create `generic` Capability Pack with basic tools/playbooks
    [x] Define Common Evidence Model (Pydantic schemas)

[x] Phase 6: Integration & API
    [x] Define LangGraph Workflow & Edges
    [x] Implement Loop Controls & Stop Conditions
    [x] Create Main Entrypoint (`main.py`)
    [x] Validation of "Read-Only" enforcement (via MCP Client)
    [x] End-to-end flow test with mock data
