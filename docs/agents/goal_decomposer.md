# Goal Decomposer Agent

> Decomposes change/request tickets into structured fulfillment goals instead of hypotheses.

## Overview

The Goal Decomposer (`src/agents/goal_decomposer.py`) handles tickets where the intent is fulfillment rather than troubleshooting. When `ticket.mode` is `"change"` or `"request"`, the pipeline routes to this agent instead of hypothesis generation.

Rather than diagnosing what went wrong, the agent produces a set of `FulfillmentGoal` objects that describe what needs to be accomplished. Each goal includes preconditions that must hold before execution, validation criteria that define how to confirm completion, and optional sub-goal references that form a dependency DAG.

The agent is re-entrant. If goals from a prior decomposition are still pending or in progress, it skips re-decomposition. Completed goals from prior runs are preserved and merged with newly generated goals.

## When Called

Routed by supervisor when the ticket mode is `"change"`, no fulfillment goals exist yet, and no hypotheses have been generated (priority 7).

```python
ticket_mode = ticket.mode if ticket else "incident"
if ticket_mode == "change" and not state.get("fulfillment_goals") and not state.get("hypotheses"):
    return "goal_decomposer"
```

Return: Fixed edge → supervisor.

## Flow Diagram

```mermaid
flowchart TD
    A[ticket mode=change + components + facts] --> B{Active goals exist?}
    B -- Yes --> C[Skip re-decomposition, return case_status=modeled]
    B -- No --> D[Build context: components, facts, evidence]
    D --> E[LLM: Decompose into 1-5 fulfillment goals]
    E --> F[Merge: preserve completed + add new pending goals]
    F --> G[Return fulfillment_goals + case_status=modeled]
```

## Input / Output Contract

| Field | Type | Source |
|---|---|---|
| **Input** | | |
| `ticket` | `Ticket` | Ingestion (mode=change or request) |
| `components` | `List[Component]` | Mapper agent |
| `facts` | `Dict` | Enricher agent |
| `evidence_refs` | `List[EvidenceSnapshot]` | Evidence collector |
| `fulfillment_goals` | `List[FulfillmentGoal]` | Previous iteration |
| **Output** | | |
| `fulfillment_goals` | `List[FulfillmentGoal]` | Merged list (completed preserved + new pending) |
| `case_status` | `str` | Set to `"modeled"` |

### Input Example

```json
{
  "ticket": {
    "id": "CHG-0891",
    "mode": "change",
    "text": "Add new site-to-site VPN tunnel between FW-MAIN and FW-BRANCH-07. Use IKEv2 with AES-256-GCM.",
    "severity": "medium"
  },
  "components": [
    { "id": "fw-main", "ref": "FW-MAIN", "role": "firewall", "vendor": "fortinet" },
    { "id": "fw-branch-07", "ref": "FW-BRANCH-07", "role": "firewall", "vendor": "fortinet" }
  ],
  "facts": {},
  "evidence_refs": []
}
```

### Output Example

```json
{
  "fulfillment_goals": [
    {
      "id": "g1",
      "description": "Configure IKEv2 Phase 1 proposal on both FW-MAIN and FW-BRANCH-07 with AES-256-GCM and matching PSK or certificate authentication",
      "preconditions": ["Both firewalls are reachable and have management access", "WAN IP addresses for both endpoints are known"],
      "validation_criteria": ["IKE SA established between both peers", "Phase 1 status shows ESTABLISHED"],
      "status": "pending",
      "sub_goals": []
    },
    {
      "id": "g2",
      "description": "Configure IPsec Phase 2 selectors with the required subnet pairs and AES-256-GCM encryption",
      "preconditions": ["Phase 1 proposal configured (g1)"],
      "validation_criteria": ["IPsec SA established", "Traffic selectors match required subnets"],
      "status": "pending",
      "sub_goals": []
    },
    {
      "id": "g3",
      "description": "Add firewall policies on both ends permitting VPN traffic for the specified subnets",
      "preconditions": ["VPN tunnel established (g2)"],
      "validation_criteria": ["Policy hit counters incrementing", "Bidirectional traffic passes through tunnel"],
      "status": "pending",
      "sub_goals": []
    }
  ],
  "case_status": "modeled"
}
```

### Where Output Goes

`fulfillment_goals` are consumed by the [Supervisor](supervisor.md) (presence triggers routing to resolution planner instead of hypothesis path), [Resolution Planner](resolution_planner.md) (generates execution plan from goals), and [Response Agent](response.md) (includes goals in the final report).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LLM_MODEL_HYPOTHESIS` | `gpt-5.2` | Shared LLM profile (via `goal_decomposer` agent key) |

## Key Implementation Details

- Uses `PydanticOutputParser` with `FulfillmentGoalList` schema for structured output.
- LLM temperature set to `0.0` for deterministic goal decomposition.
- Generates 1-5 goals per decomposition pass.
- Each `FulfillmentGoal` contains: `id`, `description`, `preconditions`, `validation_criteria`, `status`, `sub_goals` (list of child goal IDs).
- Goal statuses: `pending`, `in_progress`, `completed`.
- Goals are ordered by dependency -- prerequisite goals appear first.
- `sub_goals` field references child goal IDs, forming a directed acyclic graph.
- Merge strategy: preserves goals with status `completed` from prior iterations; replaces pending/in_progress goals with fresh decomposition.
- Skip condition: if any goals have status `pending` or `in_progress`, the agent returns early to avoid disrupting active work.
- Context includes: formatted components (with vendor info), facts, and evidence summaries (max 8 items).

## See Also

- [Supervisor Agent](supervisor.md) -- routes change/request tickets to this agent
- [Resolution Planner](resolution_planner.md) -- consumes fulfillment goals to generate execution plans
