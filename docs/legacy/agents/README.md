# Agent Pipeline

> 13 specialized agents orchestrated by LangGraph. The Supervisor routes between agents based on state; sub-chains bypass the supervisor for tightly coupled sequences.

## Routing Logic

```mermaid
flowchart TD
    START(["Entry"]) --> SV["Supervisor"]

    SV -->|"!client_context"| CA["Context Agent"]
    SV -->|"!classification"| CL["Classifier"]
    SV -->|"!components"| MA["Mapper"]
    SV -->|"!evidence_refs"| EC["Evidence Collector"]
    SV -->|"pending_requirements"| RA["Response Agent"]
    SV -->|"ticket.mode=change & !fulfillment_goals"| GD["Goal Decomposer"]

    SV -->|"scoring.decision=proceed_to_plan & !plan"| RP["Resolution Planner"]
    SV -->|"scoring.decision=proceed_to_plan & plan"| RA
    SV -->|"scoring.decision=needs_more_evidence & !open_questions"| IP["Investigation Planner"]
    SV -->|"scoring.decision=needs_more_evidence & open_questions"| INV["Investigator"]
    SV -->|"scoring.decision=escalate_to_human"| RA

    SV -->|"fallback: !hypotheses"| EN["Enricher"]
    SV -->|"fallback: verified hypothesis"| RP
    SV -->|"iterations >= MAX"| RA

    CA --> SV
    CL --> SV
    MA --> SV
    IP --> SV
    GD --> SV
    RP --> SV

    EC -->|sub-chain| EN
    INV -->|sub-chain| EN
    EN --> HY["Hypothesis Agent"]
    HY --> SC["Scoring Engine"]
    SC --> SV

    RA --> END_NODE(["END"])

    style SV fill:#2d3748,color:#fff
    style SC fill:#744210,color:#fff
    style RA fill:#22543d,color:#fff
```

## Agent Summary

| # | Agent | Node Name | LLM Profile | Reads | Writes |
|---|---|---|---|---|---|
| 1 | [Supervisor](supervisor.md) | `supervisor` | — (deterministic) | `meta`, `scoring`, `case_status` | `meta.iterations`, `case_status` |
| 2 | [Context Agent](context_agent.md) | `context_agent` | `LLM_MODEL_CONTEXT` | `customer_id` | `client_context`, `topology_nodes`, `topology_edges` |
| 3 | [Classifier](classifier.md) | `classifier_agent` | `LLM_MODEL_CLASSIFIER` | `ticket.text` | `classification` |
| 4 | [Mapper](mapper.md) | `mapper_agent` | `LLM_MODEL_MAPPER` | `ticket`, `client_context` | `components` |
| 5 | [Evidence Collector](evidence_collector.md) | `evidence_collector` | `LLM_MODEL_EVIDENCE_COLLECTOR` | `components`, `ticket`, `path_analysis` | `evidence_refs` |
| 6 | [Enricher](enricher.md) | `enricher_agent` | `LLM_MODEL_ENRICHER` | `evidence_refs`, `facts`, `topology_*` | `facts`, `structured_facts`, `topology_nodes`, `topology_edges` |
| 7 | [Hypothesis](hypothesis.md) | `hypothesis_agent` | `LLM_MODEL_HYPOTHESIS` | `facts`, `ticket`, `topology_*`, `baselines`, `known_changes` | `hypotheses`, `path_analysis` |
| 8 | [Scoring](scoring.md) | `scoring_agent` | — (deterministic) | `hypotheses`, `evidence_refs`, `facts`, `ticket.severity`, `open_questions` | `scoring` |
| 9 | [Investigation Planner](investigation_planner.md) | `investigation_planner` | `LLM_MODEL_HYPOTHESIS` | `hypotheses`, `facts`, `evidence_refs` | `open_questions` |
| 10 | [Goal Decomposer](goal_decomposer.md) | `goal_decomposer` | `LLM_MODEL_HYPOTHESIS` | `ticket`, `client_context`, `classification` | `fulfillment_goals` |
| 11 | [Investigator](investigator.md) | `investigator_agent` | `LLM_MODEL_INVESTIGATOR` | `hypotheses`, `open_questions`, `components` | `evidence_refs`, `open_questions.status` |
| 12 | [Resolution Planner](resolution_planner.md) | `planner_agent` | `LLM_MODEL_PLANNER` | `ticket`, `hypotheses`, `facts`, `evidence_refs` | `plan` |
| 13 | [Response](response.md) | `response_agent` | `LLM_MODEL_RESPONSE` | entire state | `final_answer`, `handoff` |

## Sub-Chains

These fixed-edge chains bypass the supervisor for tightly coupled processing:

```
evidence_collector  → enricher → hypothesis → scoring → supervisor
investigator        → enricher → hypothesis → scoring → supervisor
```

Every evidence-gathering action triggers fact extraction, hypothesis update, and scoring before the supervisor re-evaluates.

## Case Status Lifecycle

```mermaid
stateDiagram-v2
    [*] --> new : Supervisor (first pass)
    new --> triaged : Context Agent
    triaged --> modeled : Mapper
    modeled --> planned : Evidence Collector
    planned --> investigating : Investigator
    investigating --> synthesizing : Enricher/Hypothesis
    synthesizing --> resolved : Response Agent
    synthesizing --> investigating : Scoring (needs_more_evidence)
    synthesizing --> blocked : Scoring (escalate)
    blocked --> needs_human : Response Agent
```

## See Also

- [Pipeline Diagram](../README.md) - Full system pipeline
- [Architecture Overview](../architecture/overview.md) - System-level design
- [Scoring Decision Gate](scoring.md) - How routing decisions are made
