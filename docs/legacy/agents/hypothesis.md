# Hypothesis Agent

> Generates ranked root cause hypotheses and performs path analysis on the topology graph.

## Overview

The Hypothesis agent (`src/agents/hypothesis.py`) is the core reasoning engine of the pipeline. It takes enriched facts, topology, and ticket context to produce ranked hypotheses about root cause (for incidents) or system state (for validation inquiries).

The agent makes two LLM calls. The first generates or updates a ranked list of `Hypothesis` objects, each with supporting/disconfirming facts, evidence references, confidence scores, and suggested next playbooks. The second call performs path analysis over the topology graph, identifying candidate flow paths, likely breakpoints, missing evidence, and suggested read-only diagnostic probes.

The agent operates iteratively. On subsequent passes it receives its own prior hypotheses and updates their status based on new facts: `proposed` to `verifying`, `verifying` to `verified` or `rejected`. It preserves hypothesis IDs across iterations for traceability.

A dual-role adaptation mechanism inspects ticket intent. For validation/inquiry tickets, the agent formulates neutral verification hypotheses. For incident/problem tickets, it formulates troubleshooting hypotheses targeting root cause. The configuration-first principle is enforced: hypotheses must be verifiable via existing configuration rather than live traffic analysis.

## When Called

Invoked via fixed sub-chain edge from the [Enricher](enricher.md), not by the supervisor directly.

```python
# Fixed edge — not supervisor-routed
workflow.add_edge("enricher_agent", "hypothesis_agent")
```

Return: Fixed edge → [Scoring Agent](scoring.md).

## Flow Diagram

```mermaid
flowchart TD
    A[ticket + facts + topology + client_context] --> B{enricher_skipped?}
    B -- Yes --> C[Return existing hypotheses unchanged]
    B -- No --> D[Call 1: Hypothesis Generation - LLM]
    D --> E[Ranked List of Hypothesis objects]
    E --> F{Topology edges exist?}
    F -- No --> G[Return hypotheses + case_status=modeled]
    F -- Yes --> H[Call 2: Path Analysis - LLM]
    H --> I[PathAnalysis: candidate_paths + breakpoints]
    I --> J[Return hypotheses + path_analysis + case_status=modeled]
```

## Input / Output Contract

| Field | Type | Source |
|---|---|---|
| **Input** | | |
| `ticket` | `Ticket` | Ingestion |
| `facts` | `Dict` | Enricher agent |
| `structured_facts` | `List[Fact]` | Enricher agent |
| `topology_nodes` | `List[TopologyNode]` | Enricher agent |
| `topology_edges` | `List[TopologyEdge]` | Enricher agent |
| `client_context` | `ClientContext` | Context agent (baselines, known_changes) |
| `hypotheses` | `List[Hypothesis]` | Previous iteration (for refinement) |
| `meta` | `Dict` | Enricher skip flag |
| **Output** | | |
| `hypotheses` | `List[Hypothesis]` | Ranked hypotheses with status, evidence_refs, confidence |
| `path_analysis` | `PathAnalysis` | Candidate paths, breakpoints, missing evidence, probes |
| `case_status` | `str` | Set to `"modeled"` |

### Input Example

```json
{
  "ticket": { "id": "INC-4012", "mode": "incident", "text": "Kerberos errors in event logs. DC-NORTH, ntp-pool.corp.local." },
  "facts": { "ntp_offset_dc_north": "+347 seconds", "ntp_source": "ntp-pool.corp.local" },
  "structured_facts": [
    { "key": "ntp_offset_dc_north", "value": "+347 seconds", "source_evidence_id": "ev-001", "confidence": 1.0 }
  ],
  "topology_nodes": [
    { "id": "dc-north", "node_type": "server", "label": "DC-NORTH" },
    { "id": "ntp-pool", "node_type": "service", "label": "ntp-pool.corp.local" }
  ],
  "topology_edges": [
    { "source_id": "dc-north", "target_id": "ntp-pool", "relation": "depends_on", "confidence": 0.9 }
  ],
  "client_context": { "customer_id": "tenant_acme", "baselines": [{ "component_id": "dc-north", "metric": "ntp_offset", "normal_value": "< 5 seconds" }] }
}
```

### Output Example

```json
{
  "hypotheses": [
    {
      "id": "h1",
      "summary": "NTP time skew on DC-NORTH exceeds Kerberos tolerance (5 min), causing authentication failures",
      "required_facts": ["ntp_offset_dc_north", "kerberos_max_tolerance"],
      "supporting_facts": ["ntp_offset_dc_north"],
      "evidence_refs": ["ev-001"],
      "confidence": 0.75,
      "rank": 1,
      "status": "proposed",
      "next_playbooks": ["check_w32time_config", "check_kerberos_policy"],
      "rationale": "347-second NTP offset exceeds the default Kerberos 5-minute tolerance. Baseline shows normal offset < 5 seconds."
    }
  ],
  "path_analysis": {
    "candidate_paths": [
      { "path_id": "p1", "source": "client-workstation", "destination": "dc-north", "hops": ["client-workstation->dc-north"], "status": "incomplete" }
    ],
    "most_likely_breakpoints": [{ "edge": "dc-north->ntp-pool", "constraint": "ntp_sync", "reasoning": "Time source dependency broken" }],
    "suggested_probes": ["check_w32time_service_status", "query_kerberos_ticket_lifetime"]
  },
  "case_status": "modeled"
}
```

### Where Output Goes

`hypotheses` are consumed by the [Scoring Agent](scoring.md) (confidence and decision gating), [Investigation Planner](investigation_planner.md) (question generation from active hypotheses), [Investigator](investigator.md) (targeted verification), [Resolution Planner](resolution_planner.md) (plan based on verified hypothesis), and [Response Agent](response.md) (report hypothesis history). `path_analysis` is consumed by the [Evidence Collector](evidence_collector.md) (suggested probes for re-collection), [Investigation Planner](investigation_planner.md) (context for questions), and [Investigator](investigator.md) (investigation context).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LLM_MODEL_HYPOTHESIS` | `gpt-5.2` | LLM profile for both hypothesis generation and path analysis |
| `TEST_MODE_FAST` | `false` | When true, limits output to exactly 1 hypothesis |

## Key Implementation Details

- Skips entirely when `meta.enricher_skipped` is true (no new data to reason about).
- Uses `PydanticOutputParser` with `HypothesisList` schema for structured output from Call 1.
- Call 2 (path analysis) uses raw JSON output with `response_format={"type": "json_object"}`.
- Hypothesis fields: `id`, `summary`, `required_facts`, `supporting_facts`, `disconfirming_facts`, `evidence_refs`, `confidence`, `rank`, `status`, `next_playbooks`, `rationale`.
- Hypothesis statuses: `proposed`, `verifying`, `verified`, `rejected`.
- PathAnalysis contains: `candidate_paths` (each with hops, constraints, confidence, status), `most_likely_breakpoints`, `missing_evidence`, `suggested_probes`.
- Path constraint types: `reachability`, `access_control`, `configuration`, `dependency`.
- Path status values: `viable`, `blocked`, `incomplete`.
- Configuration-first principle enforced in path analysis prompts: never suggests packet captures, debug flows, or sniffers.
- State formatters (`format_topology_edges`, `format_baselines`, `format_known_changes`, `format_facts`, `format_hypotheses`) handle truncation for prompt size management.

## See Also

- [Scoring Agent](scoring.md) -- consumes hypotheses for decision gating
- [Investigation Planner](investigation_planner.md) -- generates questions from hypotheses
- [Enricher Agent](enricher.md) -- produces the facts and topology consumed here
