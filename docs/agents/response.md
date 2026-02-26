# Response Agent

## Description
The Response Agent is the final node in the graph. It compiles all the work done (hypotheses, evidence, plan) into a coherent summary and a "Handoff Package" for the human operator or external system.

## Role in Graph
- **Node Name:** `response_agent`
- **Upstream:** `supervisor` (when finishing) or `planner_agent`.
- **Downstream:** `END` (Terminates the graph execution).

## Inputs
- `state["ticket"]`: Ticket details.
- `state["hypotheses"]`: Final list of hypotheses.
- `state["plan"]`: Generated plan.
- `state["evidence_refs"]`: All collected evidence.

## Outputs
- `state["final_answer"]`: A markdown summary string.
- `state["handoff"]`: A structured object containing paths to artifacts and escalation recommendations.

## Prompts

### 1. Final Report Generation
**System:** "IT Support / Incident & Change Engineer"
**Goal:** Synthesize a professional, actionable Engineering Report.
**Context:** Receives full investigation history (Evidence, Hypothesis, Plan).
**Output Format (Markdown):**
1.  **Context:** Symptom & Scope.
2.  **Findings:** Confirmed facts.
3.  **Diagnosis:** Root Cause or Leading Hypothesis (with probability).
4.  **Troubleshooting Plan:** High-signal verification steps.
5.  **Remediation:** Implementation & Rollback plan.
6.  **Missing Info:** Minimum sufficient context needed.

## Logic
1.  **Context Aggregation:** Gathers all evidence, hypothesis reasoning, and proposed plans from the global state.
2.  **LLM Synthesis:** Uses the formatter LLM configured in `LLM_MODEL_RESPONSE` (e.g., `gpt-4o-mini`) to generate the report, ensuring it is evidence-backed (no hallucination).
3.  **Handoff Creation:** Packages artifacts for human review.
