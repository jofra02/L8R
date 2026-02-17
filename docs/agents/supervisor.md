# Supervisor Agent

## Description
The Supervisor Agent acts as the central router and state manager for the SupportAI-Agent. It does not perform complex reasoning itself but directs the execution flow based on the current state of the global context. It enforces the maximum iteration limit to prevent infinite loops.

## Role in Graph
- **Node Name:** `supervisor`
- **Type:** Router / Control Node
- **Entry Point:** Yes, this is the main entry point of the graph.

## Inputs
- `state`: The entire `GlobalState`.

## Outputs
- `state["meta"]["iterations"]`: Increments the iteration counter.
- **Routing Decision:** Returns the name of the next node to execute.

## Logic & Routing Rules

The Supervisor evaluates the state in the following order:

1.  **Safety Break:**
    -   If `state["meta"]["iterations"] >= MAX_ITERATIONS`, routes to `response_agent` (forcing a "Handoff" report).

2.  **Context & Classification & Mapping:**
    -   Ensures prerequisites (Context, Domains, Components) are present.

3.  **Evidence Collection (Initial):**
    -   If `state["evidence_refs"]` is empty, routes to `evidence_collector`.

4.  **Active Diagnosis Loop (The Core):**
    -   Checks `state["hypotheses"]`.
    -   **Success:** If there is a `verified` hypothesis, routes to `planner_agent` (or `response_agent`).
    -   **Investigation:** If there is a `proposed` hypothesis, routes to `investigator_agent`.

5.  **Quality Control & Feedback:**
    -   Before exiting to `response_agent`, it checks: "Do we have a verified diagnosis?".
    -   **Retry:** If NO and iterations < MAX, it loops back to `planner_agent` or `investigator_agent` to gather more proof.
    -   **Abort:** If NO and iterations >= MAX, it proceeds to `response_agent` but flags the report as "Inconclusive".

6.  **Final Response:**
    -   If the diagnosis is confirmed or the loop is exhausted, routes to `response_agent`.

## Interactions
The Supervisor sits at the center of the "Hub and Spoke" (or star) topology for parts of the graph, although some agents (like `Investigator` -> `Enricher` -> `Hypothesis`) form linear sub-chains that eventually loop back to the Supervisor for the next routing decision.
