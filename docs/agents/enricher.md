# Enricher Agent

## Description
The Enricher Agent analyzes the raw evidence collected by other agents (Evidence Collector, Investigator) and extracts structured "facts" or insights. This step bridges the gap between raw command output (e.g., a massive JSON blob from a firewall) and high-level reasoning.

## Role in Graph
- **Node Name:** `enricher_agent`
- **Upstream:** `evidence_collector`, `investigator_agent`
- **Downstream:** `hypothesis_agent` (typically, to feed the facts into reasoning)

## Inputs
- `state["evidence_refs"]`: List of evidence snapshots.
- `state["facts"]`: Existing facts dictionary.

## Outputs
- `state["facts"]`: Updated dictionary of facts.

## Logic
**Current Implementation (MVP):**
-   The current logic is a placeholder/simple implementation.
-   It iterates through `evidence_refs`.
-   If the tool name contains "status", it adds a simple fact like `status_{id}: "analyzed"`.

**Intended Logic (Future):**
-   This agent should use an LLM or specific parsers to extract key metrics (e.g., "CPU Load: 90%", "Port 443: Closed") from the raw evidence content.
-   It effectively "summarizes" the evidence for the Hypothesis Agent, which might not be able to ingest megabytes of raw logs.

## Interactions
It serves as a transformation layer. By decoupling collection from reasoning, it allows the reasoning agents to work with clean, normalized data.
