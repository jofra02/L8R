# Goal Decomposer Agent

> Decomposes change/request tickets into structured fulfillment goals instead of hypotheses.

## Overview

The Goal Decomposer (`src/agents/goal_decomposer.py`) handles tickets where the intent is fulfillment rather than troubleshooting. When `ticket.mode` is `"change"` or `"request"`, the pipeline routes to this agent instead of hypothesis generation.

Rather than diagnosing what went wrong, the agent produces a set of `FulfillmentGoal` objects that describe what needs to be accomplished. Each goal includes preconditions that must hold before execution, validation criteria that define how to confirm completion, and optional sub-goal references that form a dependency DAG.

The agent is re-entrant. If goals from a prior decomposition are still pending or in progress, it skips re-decomposition. Completed goals from prior runs are preserved and merged with newly generated goals.

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
