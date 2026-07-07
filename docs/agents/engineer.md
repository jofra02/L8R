# Engineer Agent

> Single ReAct agent replacing the 13-agent pipeline.

## Overview

The Engineer agent is a single LLM-powered ReAct agent built on `langgraph.prebuilt.create_react_agent`. It replaces the entire multi-agent pipeline (ContextAgent, Classifier, Mapper, EvidenceCollector, Enricher, HypothesisAgent, InvestigationPlanner, GoalDecomposer, Scoring, Investigator, ResolutionPlanner, Response, Supervisor) with one reasoning chain backed by 6 meta-tools.

The agent receives a ticket, runs a continuous reasoning loop, naturally adapts its approach based on ticket intent (incident, review, advisory, change), and produces structured output via the `submit_findings` tool. No post-hoc extraction is needed.

Activated when `PIPELINE_MODE=engineer` (the default).

## Meta-Tools

| # | Tool | Purpose |
|---|---|---|
| 1 | `query_client_db` | Load tenant context: devices, topology, baselines, recent changes |
| 2 | `load_domain_skill` | Load domain-specific investigation methodology |
| 3 | `search_tool_catalog` | Semantic search over the Qdrant tool catalog (2182 safety-filtered tools of the 2546 the gateway exposes) |
| 4 | `search_knowledge_base` | Search vendor docs, runbooks, known issues |
| 5 | `execute_tool` | Execute MCP tools against live devices (read-only) |
| 6 | `submit_findings` | Submit structured output: summary, hypotheses, facts, plan, case_status |

All tools are created via `create_engineer_tools()` in `src/agents/engineer_tools.py`. Runtime context (`customer_id`, `run_id`, `ticket_id`, `max_tool_calls`) is bound via closure. A shared `EngineerToolState` object accumulates evidence refs, topology, client context, and findings across the entire ReAct loop.

## Mandatory Tool Sequence

```
query_client_db -> load_domain_skill -> search_tool_catalog -> execute_tool (1+) -> submit_findings
```

1. **query_client_db** -- always called first. Loads the full `ClientContext` from PostgreSQL and seeds topology nodes/edges from inventory.
2. **load_domain_skill** -- called after reading the ticket and identifying the primary domain. Loads domain-specific reasoning frameworks and investigation templates.
3. **search_tool_catalog** -- semantic search over the tool catalog in Qdrant. Returns tool names, descriptions, parameter schemas, vendor, and categories. Up to 10 results per query.
4. **execute_tool** -- executes MCP tools with read-only access. Includes safety checks (blocked keywords), tenant governance, deduplication (content-addressable signatures), and automatic evidence storage. Called one or more times.
5. **submit_findings** -- called exactly once as the final action. Produces the structured output consumed by the platform.

The agent is instructed to never produce a text-only response -- every response must include a tool call. The `submit_findings` tool cannot be called until `execute_tool` has been called at least once.

## Skills System

### Base Skill

The base investigation methodology (`src/agents/skills/base_investigation.md`) is always embedded in the system prompt at module load time. It provides the core reasoning framework, output contract, and investigation methodology that applies to all domains.

### Domain Skills

Domain-specific skills are loaded on-demand via `load_domain_skill`. Each skill file lives in `src/agents/skills/` and contains domain-specific reasoning frameworks, step-by-step investigation templates, and common pitfalls.

Available domain skill files:

- `networking.md` -- networking, routing, switching, interfaces, protocols
- `tool_catalog.md` -- advanced tool catalog search techniques

New domains are added by dropping a `.md` file in `src/agents/skills/` and mapping its trigger keywords in `DOMAIN_SKILL_MAP` (`src/agents/engineer_tools.py`). Candidates like firewall/VPN/virtualization/storage skills are not yet written.

### DOMAIN_SKILL_MAP

The `DOMAIN_SKILL_MAP` dictionary maps 18 keywords to their corresponding skill files. This allows the agent to call `load_domain_skill("bgp")` and receive the networking skill.

If no mapping is found, the agent falls back to the base investigation methodology already in its system prompt. The tool returns the list of available domain skills so the agent can retry with a valid keyword.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PIPELINE_MODE` | `engineer` | `"engineer"` (current); `"pipeline"` is a deprecated legacy toggle. Note: `main.py test` and `run_mock.py` run the legacy graph unconditionally — only the API path exercises the Engineer |
| `LLM_MODEL_ENGINEER` | `gpt-5.4` | LLM model for the Engineer ReAct agent |
| `ENGINEER_MAX_TOOL_CALLS` | `30` | Maximum tool executions per investigation run |
| `ENGINEER_MAX_ITERATIONS` | `50` | Maximum ReAct loop iterations (LangGraph recursion limit) |
| `ENGINEER_TIMEOUT_SECONDS` | `600` | Total timeout for the investigation in seconds |

All variables are defined in `src/config.py` and loaded via Pydantic Settings from the `.env` file.

## Output

The `submit_findings` tool produces a structured output with five fields:

| Field | Type | Description |
|---|---|---|
| `summary` | `str` | Complete markdown report covering all sections appropriate to the ticket type |
| `hypotheses` | `list[dict]` | Ranked hypotheses with `summary`, `confidence` (0.0-1.0), `status` (verified/proposed/rejected), `evidence_refs` (EvidenceSnapshot IDs), and `rationale` |
| `facts` | `list[dict]` | Discovered facts with `key`, `value`, `source_evidence_id` (provenance), and `confidence` |
| `plan` | `dict` | Recommended actions with four sections: `diagnosis_steps`, `proposed_changes`, `validation`, `rollback`. Each step has `description`, `tool`, `expected_outcome`, and `risk` |
| `case_status` | `str` | Final status: `resolved`, `needs_human`, or `blocked` |

The engineer node (`engineer_agent_node`) converts these raw dicts into proper GlobalState models (`Hypothesis`, `Fact`, `Plan`, `PlanStep`, `ScoringResult`) before returning to the graph. A synthetic `ScoringResult` is built for frontend compatibility.

If the agent fails to call `submit_findings` (timeout, error, or omission), a fallback extractor pulls the last AI message content as a minimal summary.

## Evidence Storage

Every `execute_tool` result is automatically saved as an immutable `EvidenceSnapshot` via `EvidenceStore`. Evidence is:

- **Content-addressable**: deduplicated by a SHA-256 hash of tool name, arguments, and content.
- **Persisted to three stores**: disk (local filesystem), Qdrant (vector-indexed for semantic retrieval), and PostgreSQL (relational metadata).
- **Namespaced by tenant**: all evidence is scoped to `customer_id`.
- **Referenced by ID**: snapshot IDs are accumulated in `EngineerToolState.evidence_refs` and attached to the final findings.

Duplicate tool executions (same tool name + same arguments) are detected via signature hashing and skipped with an informative message to the agent.

## Observability

Langfuse callbacks are propagated to the entire ReAct loop via the `ainvoke` config. When Langfuse is enabled:

- A callback handler is created with metadata including `agent: "engineer"`, `ticket_id`, and `customer_id`.
- The handler is passed in the `callbacks` list of the `invoke_config` dict.
- All LLM calls, tool invocations, and reasoning steps within the ReAct loop are traced as spans under the current Langfuse trace.

This provides full observability into the agent's reasoning chain, tool selection decisions, and execution results.

## Source Files

| File | Purpose |
|---|---|
| `src/agents/engineer.py` | LangGraph node function (`engineer_agent_node`) and model conversion helpers |
| `src/agents/engineer_tools.py` | Meta-tool factory (`create_engineer_tools`) and `EngineerToolState` |
| `src/agents/engineer_prompts.py` | System prompt composition (base prompt + base investigation skill) |
| `src/agents/skills/` | Skill markdown files (base + domain-specific) |
| `src/config.py` | Configuration variables |
