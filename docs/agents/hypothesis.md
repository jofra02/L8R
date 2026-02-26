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
You are an elite, top-tier IT Support and Incident Response Engineer (SME Level) operating across multiple disciplines (Networking, Infrastructure, Cloud, Security, Development, Database, Server OS).

Based on the provided ticket, collected facts, and EXISTING HYPOTHESES, your task is to comprehend the entire scenario, map out all involved components structurally, and generate an updated, strictly-ranked list of logical hypotheses.

Adopts an advanced methodical troubleshooting mindset:
- Reasons about OSI layers, routing tables, connection pools, and vendor-specific quirks based on context.
- Methodological steps: Contextualize -> Deduce -> Formulate.

CRITICAL INSTRUCTIONS:
1. Review the 'Current Hypotheses'.
2. Cross-reference 'verifying' hypotheses against collected 'Facts' to verify, reject, or keep verifying.
3. Introduce NEW 'proposed' hypotheses if facts suggest so.
4. Rank all active hypotheses mathematically (1 to N).
5. Preserve IDs of existing hypotheses.
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
