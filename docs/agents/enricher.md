# Enricher Agent

## Description
The Enricher Agent performs **two-pass extraction** on raw evidence collected by the Evidence Collector and Investigator:
1. **Fact Extraction**: Extracts structured key-value facts (identifiers, addresses, error codes, statuses, performance metrics, configuration settings, version numbers, resource utilization, log entries, MITRE ATT&CK mappings).
2. **Topology Extraction**: Identifies entity relationships (nodes + edges) to build a comprehensive dependency graph — the system's "mental map" of all components and systems participating in the analysis scenario.

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
- LLM extracts concrete values: identifiers, addresses, error codes, statuses, performance metrics (latency, throughput, response times), configuration settings, version numbers, resource utilization, log entries.
- MITRE ATT&CK mapping included when evidence clearly suggests attack-related behavior.
- Output: JSON key-value pairs merged into `state["facts"]`.

### Pass 2: Topology Extraction
For each new evidence item:
- LLM analyzes the same evidence for entity relationships across all IT domains.
- Extracts **nodes** with types: `device`, `service`, `application`, `database`, `container`, `subnet`, `interface`, `host`, `vm`, `api`, `storage`, `cluster`, `queue`, `endpoint`, `dns_name`.
- Extracts **edges** with relation types: `connects_to`, `depends_on`, `serves`, `hosts`, `routes_to`, `calls_api`, `queries`, `reads_from`, `writes_to`, `authenticates_via`, `publishes_to`, `subscribes_to`, `replicates_to`, `load_balances`, `proxies`, `mounts`, `dns_resolves`, `policy_allow`, `policy_deny`, `nat`.
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
- **Graph Purpose**: The topology graph serves as the system's conceptual map of all entities and their relationships in the scenario under analysis. It is consumed by the Hypothesis Agent for path analysis, breakpoint detection, and reasoning about system dependencies.
