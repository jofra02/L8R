# Resolution Planner Agent

> Generates a structured, safety-first resolution plan once the scoring gate approves proceeding to plan.

## Overview

The Resolution Planner runs after the Scoring Agent emits a `proceed_to_plan` decision. It takes the verified hypothesis, collected facts, evidence snapshots, and the original ticket, then produces a four-section execution plan: diagnosis verification, proposed changes, validation, and rollback.

The agent uses Case-Based Reasoning (CBR) via `CaseRetriever` to query Qdrant for past resolved tickets with similar problems. These historical resolutions are injected into the LLM prompt so the planner can prioritize proven tools and strategies.

Every proposed change is flagged for human approval (HITL gate). Rollback steps are mandatory. Diagnosis steps are read-only verification commands that confirm the hypothesis before any mutation is attempted.

The source file is `src/agents/planner.py`; the node function is `resolution_planner_agent_node`. A backward-compatible alias `planner_agent_node` is also exported.

## When Called

Routed by supervisor when scoring returns `proceed_to_plan` and no plan exists yet (priority 9).

```python
if scoring and decision == "proceed_to_plan":
    if not state.get("plan"):
        return "planner_agent"
```

Return: Fixed edge --> supervisor.

## Flow Diagram

```mermaid
flowchart TD
    A[hypotheses + facts + evidence + ticket] --> B[Select Best Hypothesis]
    B --> C[CBR: Query Qdrant for similar resolved tickets]
    C --> D[Build prompt with facts, evidence, CBR context]
    D --> E[LLM generates Plan]
    E --> F[Plan]

    F --> G[diagnosis_steps]
    F --> H[proposed_changes]
    F --> I[validation]
    F --> J[rollback]

    G --> K["Read-only verification commands"]
    H --> L["Remediation actions (require HITL approval)"]
    I --> M["Post-change verification steps"]
    J --> N["Revert steps if changes fail"]
```

## Input / Output Contract

### Input

| Field | Type | Source |
|---|---|---|
| `ticket` | `Ticket` | Ingestion |
| `hypotheses` | `List[Hypothesis]` | HypothesisAgent (best/verified selected by rank) |
| `facts` | `Dict` | Enricher |
| `evidence_refs` | `List[EvidenceSnapshot]` | EvidenceCollector / Investigator |
| `customer_id` | `str` | State (used for tenant-scoped CBR retrieval) |

### Output

| Field | Type | Description |
|---|---|---|
| `plan` | `Plan` | Contains `diagnosis_steps`, `proposed_changes`, `validation`, `rollback` |
| `case_status` | `str` | Set to `"resolved"` on success |

Each `PlanStep` contains: `step_id`, `description`, `tool`, `args`, `expected_outcome`, and risk level.

### Input Example

```json
{
  "ticket": { "id": "INC-4012", "mode": "incident", "text": "Kerberos errors. DC-NORTH, ntp-pool.corp.local.", "severity": "high" },
  "hypotheses": [
    { "id": "h1", "summary": "NTP time skew exceeds Kerberos tolerance", "status": "verified", "rank": 1, "rationale": "347-second offset exceeds 300-second default Kerberos tolerance" }
  ],
  "facts": { "ntp_offset_dc_north": "+347 seconds", "kerberos_max_tolerance": "300 seconds", "w32time_ntp_peer": "local CMOS clock" },
  "evidence_refs": [{ "id": "ev-001" }, { "id": "ev-002" }, { "id": "ev-003" }],
  "customer_id": "tenant_acme"
}
```

### Output Example

```json
{
  "plan": {
    "diagnosis_steps": [
      { "step_id": "d1", "description": "Verify current NTP offset on DC-NORTH", "tool": "get_ntp_status", "args": { "device": "dc-north" }, "expected_outcome": "Offset > 300 seconds confirmed", "risk": "low" }
    ],
    "proposed_changes": [
      { "step_id": "c1", "description": "Reconfigure W32Time to use ntp-pool.corp.local as primary NTP peer", "tool": "set_ntp_peer", "args": { "device": "dc-north", "peer": "ntp-pool.corp.local" }, "expected_outcome": "NTP peer updated and time sync initiated", "risk": "medium" },
      { "step_id": "c2", "description": "Force NTP resynchronization", "tool": "force_ntp_sync", "args": { "device": "dc-north" }, "expected_outcome": "NTP offset reduced to < 5 seconds", "risk": "low" }
    ],
    "validation": [
      { "step_id": "v1", "description": "Verify NTP offset is within Kerberos tolerance", "tool": "get_ntp_status", "args": { "device": "dc-north" }, "expected_outcome": "Offset < 300 seconds", "risk": "low" },
      { "step_id": "v2", "description": "Test Kerberos authentication from Building-7 workstation", "tool": "test_kerberos_auth", "args": { "target": "dc-north" }, "expected_outcome": "Authentication succeeds", "risk": "low" }
    ],
    "rollback": [
      { "step_id": "r1", "description": "Revert NTP peer configuration to previous setting", "tool": "set_ntp_peer", "args": { "device": "dc-north", "peer": "local_cmos" }, "expected_outcome": "NTP peer reverted", "risk": "low" }
    ]
  },
  "case_status": "resolved"
}
```

### Where Output Goes

`plan` is consumed by the [Supervisor](supervisor.md) (checks plan existence to route to response) and by the [Response Agent](response.md) (includes the full plan in the final technical report).

## Configuration

| Variable | Purpose |
|---|---|
| `LLM_MODEL_PLANNER` | Model used for plan generation (e.g., `gpt-5.2`) |
| `LLM_TEMPERATURE_DEFAULT` | Set to `0.0` for deterministic, precise planning |

## Key Implementation Details

- **CBR retrieval**: uses `CaseRetriever` backed by Qdrant `resolved_tickets` collection. Retrieves up to 3 similar cases. Failures are non-fatal; the planner proceeds without historical context.
- **Prompt structure**: system message defines safety-first guidelines; user message injects ticket text, hypothesis summary/rationale, facts summary, evidence summary (last 10 items), CBR context, and Pydantic format instructions.
- **Output parsing**: uses `PydanticOutputParser` with the `Plan` model for structured JSON output directly from the LLM.
- **Safety-first design**: diagnosis steps are read-only verification; proposed changes require HITL approval before execution; rollback is mandatory.
- **Fallback**: on LLM failure, returns an empty `Plan()` (signals human intervention required).
- **Internal facts excluded**: facts prefixed with `_` are filtered out of the prompt context.

## See Also

- [agents/response.md](response.md) -- consumes the plan for final report synthesis
- [agents/scoring.md](scoring.md) -- gates entry to the planner via `proceed_to_plan`
- [architecture/safety_and_governance.md](../architecture/safety_and_governance.md) -- HITL approval framework
