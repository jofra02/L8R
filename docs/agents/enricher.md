# Enricher Agent

## Description
The Enricher Agent performs **two-pass extraction** on raw evidence collected by the Evidence Collector and Investigator:
1. **Fact Extraction**: Extracts structured key-value facts (IPs, statuses, configs, MITRE ATT&CK mappings).
2. **Topology Extraction**: Identifies entity relationships (nodes + edges) to build the dependency graph.

## Role in Graph
- **Node Name:** `enricher_agent`
- **Upstream:** `evidence_collector`, `investigator_agent`
- **Downstream:** `hypothesis_agent`

## Inputs
- `state["evidence_refs"]`: List of evidence snapshots.
- `state["facts"]`: Existing facts dictionary.
- `state["topology_nodes"]`: Existing topology nodes.
- `state["topology_edges"]`: Existing topology edges.
- `state["components"]`: Known components for topology context.

## Outputs
- `state["facts"]`: Updated dictionary of extracted facts.
- `state["topology_nodes"]`: Merged/deduplicated topology nodes.
- `state["topology_edges"]`: Merged/deduplicated topology edges.

## Processing Pipeline

### Pass 1: Fact Extraction
For each new evidence item:
- Loads raw content from `EvidenceStore` (filesystem).
- Compresses large payloads via `json_compressor`.
- LLM extracts concrete values: IPs, error codes, statuses, configs, firmware versions.
- MITRE ATT&CK mapping included when evidence suggests attack-related behavior.
- Output: JSON key-value pairs merged into `state["facts"]`.

### Pass 2: Topology Extraction
For each new evidence item:
- LLM analyzes the same evidence for entity relationships.
- Extracts **nodes** (devices, subnets, interfaces, services) and **edges** (routes_to, policy_allow, depends_on, etc.).
- Each edge carries a `confidence` score (tool output = high, inferred = low).
- Output: `TopologyNode[]` and `TopologyEdge[]`.

### Deduplication
- **Nodes**: Deduplicated by `id` — first seen wins.
- **Edges**: Deduplicated by `(source_id, target_id, relation)` — higher confidence wins.
- Merged with existing topology from previous iterations.

## Key Logic & Interactions
- **LLM Model:** Uses `LLM_MODEL_ENRICHER` (e.g., `gpt-5-mini`) — fast extraction, no deep reasoning needed.
- **Incremental**: Tracks `_processed_evidence_ids` in facts to avoid re-processing evidence.
- **Skip Logic**: If no new evidence exists, returns immediately with `enricher_skipped=True` flag.
