# Planner Agent

## Description
The Planner Agent creates a structured, safe plan to resolve the issue once a leading hypothesis has been identified. It outlines the steps for verification, remediation/change, validation, and rollback.

## Role in Graph
- **Node Name:** `planner_agent`
- **Upstream:** `supervisor` (typically when a hypothesis is strong enough or max iterations reached)
- **Downstream:** `supervisor` (then to `response_agent`)

## Inputs
- `state["ticket"]`: Ticket details.
- `state["hypotheses"]`: The list of hypotheses. It typically focuses on the top-ranked one (`hypotheses[0]`).

## Outputs
- `state["plan"]`: A `Plan` object containing lists of `PlanStep`s for diagnosis, changes, validation, and rollback.

## Prompts

### Plan Drafting
**System:**
```text
You are an expert Subject Matter Expert. Create a safe, step-by-step plan to verify the hypothesis and resolve the issue. Do NOT include steps that modify the system state without approval. Focus on diagnosis and verification first.
```

**User:**
```text
Ticket: {text}

Hypothesis: {hypothesis_text}

{format_instructions}
```

## Key Logic & Interactions
-   **Safety First:** The system prompt explicitly instructs to avoid unapproved state modifications.
-   **Structure:** The output is broken down into logical phases (Diagnosis, Proposed Changes, Validation, Rollback) using Pydantic models, making it easy to present to a human for approval (HITL).
