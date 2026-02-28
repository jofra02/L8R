# Planner Agent

## Description
The Planner Agent creates a structured, safe plan to resolve the issue once a leading hypothesis has been identified. It outlines the steps for verification, remediation/change, validation, and rollback. It leverages Case-Based Reasoning (CBR) to learn from historically resolved tickets.

## Role in Graph
- **Node Name:** `planner_agent`
- **Upstream:** `supervisor` (typically when a hypothesis is strong enough or max iterations reached)
- **Downstream:** `supervisor` (then to `response_agent`)

## Inputs
- `state["ticket"]`: Ticket details.
- `state["hypotheses"]`: The list of hypotheses. Focuses on the top-ranked one.
- `state["facts"]`: Collected facts for context.
- `state["evidence_refs"]`: Gathered evidence for context.

## Outputs
- `state["plan"]`: A `Plan` object containing lists of `PlanStep`s for diagnosis, changes, validation, and rollback.

## Prompts

### Plan Drafting
**System:**
```text
You are an expert Senior IT Support Engineer planning resolution strategies. Your goal is to create a safe, step-by-step Execution Plan to verify the active hypothesis and resolve the issue.

GUIDELINES:
1. Safety First: Do NOT modify system state (restarts, configuration changes, destructive operations) without first verifying the diagnosis.
2. Diagnosis Steps: actions to confirm the hypothesis.
3. Proposed Changes: actions to fix the root cause (once verified).
4. Validation: steps to confirm the fix works.
5. Rollback: steps to revert if the fix fails.
6. Learn from History: Review the 'Relevant Past Cases' below. If a similar issue was resolved before, prioritize those tools and steps.
```

**User:**
```text
Ticket: {ticket_text}

Active Hypothesis: {hypothesis_summary}
{hypothesis_rationale}

Facts Already Collected: {facts_summary}

Evidence Already Gathered: {evidence_summary}

{cbr_context}

{format_instructions}
```

## Key Logic & Interactions
- **LLM Model:** Uses `LLM_MODEL_PLANNER` (e.g., `gpt-5.2` with temperature 0.0) for precise and deterministic planning.
- **Case-Based Reasoning (CBR):** Consults the Qdrant vector database via `CaseRetriever` to find similar historically resolved tickets before formulating the plan.
- **Safety First:** The system prompt explicitly instructs to avoid unapproved state modifications — restarts, configuration changes, and destructive operations all require HITL approval.
- **Structure:** The output is broken down into logical phases (Diagnosis, Proposed Changes, Validation, Rollback) using Pydantic models, making it easy to present to a human for approval (HITL).
