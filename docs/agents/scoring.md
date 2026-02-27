# Scoring / Decision Engine

## Purpose

Deterministic gate between hypothesis verification and planning. Runs after every hypothesis update and decides whether the agent chain has enough evidence to proceed.

## Position in Graph

```
enricher → hypothesis → scoring → supervisor
```

## Input (Reads from GlobalState)

| Field | Usage |
|:---|:---|
| `hypotheses` | Best hypothesis confidence, status, required/supporting facts |
| `evidence_refs` | Evidence item count |
| `facts` | Fact density (non-internal keys) |
| `ticket.severity` | Severity weight for risk score |
| `pending_requirements` | Immediate escalation if any exist |

## Output (Writes to GlobalState)

| Field | Type | Description |
|:---|:---|:---|
| `scoring.risk_score` | float (1-10) | `severity_weight × (2 − confidence) × 2.5` |
| `scoring.confidence` | float (0-1) | `hyp_confidence×0.5 + evidence_coverage×0.3 + fact_density×0.2` |
| `scoring.evidence_coverage` | float (0-1) | Supporting facts / required facts |
| `scoring.decision` | enum | `proceed_to_plan` · `needs_more_evidence` · `escalate_to_human` |
| `scoring.rationale` | string | Human-readable explanation |
| `scoring.missing_facts` | list | Facts still needed |

## Decision Logic

| Condition | Decision |
|:---|:---|
| `pending_requirements` not empty | `escalate_to_human` |
| Hypothesis verified + confidence ≥ 0.7 | `proceed_to_plan` |
| Confidence ≥ 0.7 + evidence ≥ 2 | `proceed_to_plan` |
| Confidence < 0.3 + severity critical/high | `escalate_to_human` |
| Otherwise | `needs_more_evidence` |

## Design Notes

- **No LLM call** — pure deterministic heuristics for speed and reliability
- Thresholds are constants in `scoring.py` (`CONFIDENCE_PROCEED = 0.7`, `CONFIDENCE_ESCALATE = 0.3`)
- Severity weights: critical=4, high=3, medium=2, low=1
