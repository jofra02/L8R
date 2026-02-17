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

[ ] Phase 7: Version Control & Distribution
    [ ] Initialize Git Repository & .gitignore
    [ ] Push to GitHub (Manual/CLI)

[x] Phase 8: Data Seeding & Onboarding
    [x] Design Context Seeding Strategy (YAML/JSON -> Postgres)
    [x] Design Knowledge Base Seeding Strategy (Docs -> Qdrant)
    [x] Implement Seeding Scripts (`seed_context.py`, `seed_kb.py`)
    [x] Add CLI commands for seeding (`init-db`, `register-tenant`, `seed*`)

[x] Phase 9: Model Governance (LLM Profiles)
    [x] Design Profile Strategy (Main: Reasoning, Fast: Speed)
    [x] Update `src/config.py` with LLM settings
    [x] Update `src/config.py` with LLM settings
    [x] Refactor `LLMFactory` in `src/core/llm.py`

[x] Phase 10: Audit System (Bitacora)
    [x] Implement `AuditService` (`src/core/audit.py`)
    [x] Implement Graph Decorator (`src/agent_graph.py`)
    [x] Integrate Run Creation in `src/main.py`
    [x] Integrate Run Creation in `src/main.py`
    [x] Verify Audit Logs in Database

[x] Phase 13: External MCP Support
    [x] Install `mcp` library
    [x] Refactor `src/mcp/client.py` to use `mcp` SDK
    [x] Add MCP Server Configuration to `src/config.py`
    [x] specific `src/core/registry.py` to load external tools

[x] Phase 14: MCP Refinement (SSE & Stdio)
    [x] Update `src/config.py` with placeholders
    [x] Refactor `src/mcp/client.py` to support SSE
    [x] Update `docs/mcp_integration.md`

[x] Phase 17: Vendor Agnostic Logic & Brute Force Fallback
    [x] Add `vendor` field to `Component` model
    [x] Update `Mapper` agent to infer vendor
    [x] Refactor `EvidenceCollector` for Multi-Tool Selection
    [x] Implement Brute Force Fallback
    [x] Verify with FortiGate test case

[x] Phase 15: Smart Evidence Collection
    [x] Implement `search_tools` in `Registry`
    [x] Update `EvidenceCollector` with LLM logic (Search -> Select -> Execute)
    [x] Verify with FortiGate test case

[x] Phase 16: Documentation Updates
    [x] Create `docs/evidence_collector_technical.md`
    [x] Update `README.md` with link to new doc

[x] Phase 11: Documentation
    [x] Update `README.md` (Architecture, Setup, Usage)
    [x] Create/Update `onboarding_plan.md` (if needed)

[x] Phase 12: MCP Integration Guide
    [x] Create `docs/mcp_integration.md`
    [x] Explain Client, Registry, and Configuration
    [x] Provide "Hello World" connection example

[ ] Phase 18: Active Diagnosis Loop
    [ ] Update `Hypothesis` model (Rank, Status)
    [ ] Refactor `Hypothesis` agent for Ranking & Verification Check
    [ ] Create `Investigator` agent (Targeted Tools vs Hypothesis)
    [ ] Update `Supervisor` for Investigation Loop
    [ ] Verify with FortiGate test case (Mocking "Proof")
