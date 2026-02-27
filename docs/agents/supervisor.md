# Supervisor Agent

## Description
The Supervisor Agent acts as the central router and state manager. It does not perform complex reasoning itself but directs execution flow based on the current state. It enforces iteration limits to prevent infinite loops and uses the **Scoring Engine's decision gate** to determine next steps.

## Role in Graph
- **Node Name:** `supervisor`
- **Type:** Router / Control Node
- **Entry Point:** Yes, this is the main entry point of the graph.

## Inputs
- `state`: The entire `GlobalState`.

## Outputs
- `state["meta"]["iterations"]`: Increments the iteration counter.
- **Routing Decision:** Returns the name of the next node to execute.

## Routing Pipeline

The Supervisor evaluates the state in priority order:

| Priority | Condition | Route |
|:---|:---|:---|
| 0 | `iterations >= MAX_ITERATIONS` | `response_agent` (forced exit) |
| 1 | No `client_context` | `context_agent` |
| 2 | No `classification` | `classifier_agent` |
| 3 | No `components` | `mapper_agent` |
| 4 | No `evidence_refs` | `evidence_collector` |
| 5 | `pending_requirements` exist | `response_agent` (HITL pause) |
| 6 | `scoring.decision = proceed_to_plan` | `planner_agent` (or `response_agent` if plan exists) |
| 7 | `scoring.decision = needs_more_evidence` | `investigator_agent` (if active hypotheses) or `evidence_collector` |
| 8 | `scoring.decision = escalate_to_human` | `response_agent` |
| 9 | Verified hypothesis (pre-scoring) | `planner_agent` |
| 10 | Active hypotheses (pre-scoring) | `investigator_agent` |
| 11 | Default | `response_agent` |

## Iteration Limits
- **Normal mode:** 15 iterations max
- **Fast mode (`TEST_MODE_FAST`):** 8 iterations max

## Resume Handling
On resume (after HITL pause):
- `scoring` is reset to `None` so the supervisor doesn't re-use old decisions.
- `plan` is reset to `None` for re-planning.
- `path_analysis` is reset to `None` for re-evaluation.
- `iterations` is reset to 0.

## Interactions
The Supervisor sits at the center of the graph. Some agents form fixed sub-chains:
```
evidence_collector → enricher → hypothesis → scoring → supervisor
investigator       → enricher → hypothesis → scoring → supervisor
```
