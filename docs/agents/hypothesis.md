# Hypothesis Agent

## Description
The Hypothesis Agent is the reasoning engine of the system. It consumes the ticket details and all collected "facts" to generate a ranked list of potential explanations (hypotheses) for the issue. It also re-evaluates existing hypotheses as new evidence comes in.

## Role in Graph
- **Node Name:** `hypothesis_agent`
- **Upstream:** `enricher_agent`
- **Downstream:** `supervisor` (which will then likely route to `investigator_agent` or `planner_agent`)

## Inputs
- `state["ticket"]`: Ticket text.
- `state["facts"]`: Structured facts extracted by the Enricher.
- `state["hypotheses"]`: Existing hypotheses (if any).

## Outputs
- `state["hypotheses"]`: A list of `Hypothesis` objects, ranked by probability.

## Prompts

### Hypothesis Generation & Ranking
**System:**
```text
You are an expert IT Support AI. 
Based on the ticket and collected facts, generate potential hypotheses for the root cause (if incident) or implementation path (if change).

CRITICAL INSTRUCTIONS:
1. Rank your hypotheses from most likely (1) to least likely.
2. Assign a 'rank' integer to each.
3. Set 'status' to 'proposed' for new hypotheses.
4. If existing hypotheses are passed in context, re-evaluate them based on new evidence.
5. Identify what SPECIFIC evidence is missing to confirm/deny each hypothesis.
```

**User:**
```text
Ticket: {text}

Facts:
{facts}

{format_instructions}
```

## Key Logic & Interactions
-   **Ranking:** The agent explicitly ranks hypotheses. The `Supervisor` uses this rank to decide which hypothesis to verify first.
-   **Status Management:** New hypotheses start as `proposed`. The `Investigator` agent changes them to `verifying` and eventually `verified` or `rejected` (in a future iteration of this agent).
-   **Dynamic Updates:** This agent runs in a loop. In the first pass, it guesses based on the ticket. In subsequent passes, it refines its guesses based on the 'facts' that verify or disprove previous assumptions.
