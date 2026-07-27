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
| 3 | `search_tool_catalog` | Semantic search over the Qdrant tool catalog (2220 safety-filtered tools of the 2776 the gateway exposes), scoped to the tenant's appliance-pack versions |
| 4 | `search_knowledge_base` | Search vendor docs, runbooks, known issues |
| 5 | `execute_tool` | Execute MCP tools against live devices (read-only, direct via the shared `execute_mcp_tool` helper — no AdaptiveExecutor) |
| 6 | `submit_findings` | Submit structured output: summary, hypotheses, facts, plan, case_status |

All tools are created via `create_engineer_tools()` in `src/agents/engineer_tools.py`. Runtime context (`customer_id`, `run_id`, `ticket_id`, `max_tool_calls`) is bound via closure. A shared `EngineerToolState` object accumulates evidence refs, topology, client context, and findings across the entire ReAct loop.

## Mandatory Tool Sequence

```
query_client_db -> load_domain_skill -> search_tool_catalog -> execute_tool (1+) -> submit_findings
```

1. **query_client_db** -- always called first. Loads the full `ClientContext` from PostgreSQL and seeds topology nodes/edges from inventory.
2. **load_domain_skill** -- called after reading the ticket and identifying the primary domain. Loads domain-specific reasoning frameworks and investigation templates.
3. **search_tool_catalog** -- semantic search over the tool catalog in Qdrant. Returns tool names, descriptions, parameter schemas (one line per parameter: type, format, enum values, required flag), vendor, and categories. Up to 10 results per query. Results are **version-scoped**: the allowed `pack_key`s are derived from the tenant's managed devices (`src/core/pack_matching.py` — exact version, then major.minor, then over-inclusive fallback); tools without pack identity always pass, and a tenant with no managed devices searches unscoped.
4. **execute_tool** -- executes MCP tools with read-only access through the shared `execute_mcp_tool` helper (`src/core/mcp_executor.py`): safety filter (blocked keywords) → tenant governance → registry resolution → framework-side `tenant` injection → execution. Adds run-local deduplication (SHA-256 signature over tool name + the LLM's arguments — a repeat call is skipped with a message), a `max_tool_calls` cap, automatic evidence storage, and a `tool_calls_audit` record per call. Called one or more times.
5. **submit_findings** -- called exactly once as the final action. Produces the structured output consumed by the platform.

The sequence is enforced by prompt rules, not code: the agent is instructed to never produce a text-only response (every response must include a tool call) and to never call `submit_findings` until `execute_tool` has run at least once.

## Skills System

### Base Skill

The base investigation methodology (`src/agents/skills/base_investigation.md`, "Logical Investigation Method") is always embedded in the system prompt at module load time. It is a concise, domain-agnostic causal reasoning method: numbered process steps (failure definition, dependency profiles, evidence ledger, diverse hypotheses with pre-registered predictions, attribution and exoneration rules, forward causal verification), a metacognitive Pre-Closure Check, funnel triggers for `lateral_thinking` and `logs`, and the reasoning format `Symptom → Model → Hypotheses → Predictions → Discriminating test → Evidence → Update → Causal chain → Calibrated conclusion`. The Output Contract (the `submit_findings` summary structure per request mode) lives directly in `ENGINEER_SYSTEM_PROMPT` (`src/agents/engineer_prompts.py`), not in the skill.

The base skill is also the canonical style reference for authoring new skills — see `docs/agents/skill_authoring.md`.

### Domain Skills

Domain-specific skills are loaded on-demand via `load_domain_skill`. Each skill file lives in `src/agents/skills/` and contains domain-specific reasoning frameworks, step-by-step investigation templates, and common pitfalls.

Available domain skill files:

- `networking.md` -- networking, routing, switching, interfaces, protocols
- `tool_catalog.md` -- advanced tool catalog search techniques
- `fortigate_licensing.md` -- FortiGate license/entitlement investigation (verified tool anchors)
- `fortigate_logs.md` -- FortiGate log retrieval across storage backends (verified tool anchors)
- `flow_verification.md` -- control-point flow verification: is the firewall affecting a specific application flow (verified tool anchors)
- `fortiedr.md` -- FortiEDR endpoint security: collectors, security events, threat hunting (verified tool anchors)
- `fortiedr_triage.md` -- FortiEDR event triage: verdict adjudication (malicious / benign / false positive)
- `lateral_thinking.md` -- investigation re-framing techniques for stalled cases

New domains are added by dropping a `.md` file in `src/agents/skills/` and mapping its trigger keywords in `DOMAIN_SKILL_MAP` (`src/agents/engineer_tools.py`). See `docs/agents/skill_authoring.md` for the authoring format, tool anchor contract, and registration checklist.

### DOMAIN_SKILL_MAP

The `DOMAIN_SKILL_MAP` dictionary maps trigger keywords to their corresponding skill files. This allows the agent to call `load_domain_skill("bgp")` and receive the networking skill.

If no mapping is found, the agent falls back to the base investigation methodology already in its system prompt. The tool returns the list of available domain skills so the agent can retry with a valid keyword.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PIPELINE_MODE` | `engineer` | `"engineer"` (current); `"pipeline"` is a deprecated legacy toggle. Note: `main.py test` and `run_mock.py` run the legacy graph unconditionally — only the API path exercises the Engineer |
| `LLM_MODEL_ENGINEER` | `gpt-5.4` | LLM model for the Engineer ReAct agent |
| `ENGINEER_MAX_TOOL_CALLS` | `30` | Maximum tool executions per investigation run |
| `ENGINEER_MAX_ITERATIONS` | `50` | Maximum ReAct loop iterations (LangGraph recursion limit) |
| `ENGINEER_TIMEOUT_SECONDS` | `600` | Total timeout for the investigation in seconds |
| `LLM_REASONING_EFFORT_ENGINEER` | `None` | Reasoning effort for the Engineer's LLM. The global `LLM_REASONING_EFFORT` deliberately does **not** apply to the engineer — unset means no `reasoning_effort` is sent |

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

If the agent fails to call `submit_findings`, the outcome depends on why:

- **Omission** (loop ended normally without calling it): a fallback extractor pulls the last AI message content as a minimal summary (`case_status: resolved`).
- **Timeout** (`ENGINEER_TIMEOUT_SECONDS` exceeded): synthetic "Investigation Interrupted" findings with `case_status: blocked` and the evidence count collected so far.
- **Loop error** (ReAct loop raised before any findings): the node re-raises, so the run is persisted as `failed` instead of `completed` with a blank report.

## Evidence Storage

Every `execute_tool` result is automatically saved as an immutable `EvidenceSnapshot` via `EvidenceStore`. Evidence is:

- **Content-addressable**: the snapshot ID (`ev_<hash8>`) and on-disk filename derive from a SHA-256 hash of the result content, so identical content is stored once.
- **Persisted to three stores**: disk (local filesystem), Qdrant (vector-indexed for semantic retrieval), and PostgreSQL (relational metadata).
- **Namespaced by tenant**: all evidence is scoped to `customer_id`.
- **Referenced by ID**: snapshot IDs are accumulated in `EngineerToolState.evidence_refs` and attached to the final findings.

Separately from content addressing, duplicate tool **executions** are prevented up front: a per-run signature (SHA-256 over tool name + the agent's arguments, computed before tenant injection) causes an exact repeat call to be skipped with an informative message to the agent instead of re-executing.

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
| `src/core/mcp_executor.py` | Shared MCP execution helper used by `execute_tool` (safety → governance → tenant injection → execution; also used by the assessments module) |
| `src/core/pack_matching.py` | Device `os_version` → pack version matching for catalog scoping |
| `src/config.py` | Configuration variables |
