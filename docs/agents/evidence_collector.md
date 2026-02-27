# Evidence Collector Agent

## Description
The Evidence Collector Agent gathers the initial diagnostic evidence about the environment. It uses a **multi-intent approach**: the LLM generates 3-5 specific diagnostic intents, each searched independently in Qdrant for comprehensive tool coverage. When topology/path analysis exists, it prioritizes filling identified evidence gaps.

## Role in Graph
- **Node Name:** `evidence_collector`
- **Upstream:** `supervisor` (when evidence is needed)
- **Downstream:** `enricher_agent` (to parse and analyze the raw outputs)

## Inputs
- `state["ticket"]`: Ticket text to understand the issue.
- `state["components"]`: List of identified components to target.
- `state["evidence_refs"]`: Existing evidence (appends to this list).
- `state["path_analysis"]`: (optional) Path analysis with suggested probes and missing evidence.

## Outputs
- `state["evidence_refs"]`: List of new `EvidenceSnapshot` objects pointing to the collected data.

## Tool Selection Pipeline

### Step A: Multi-Intent Generation
**System:** "You are an expert IT Systems Engineer performing systematic diagnostics."

For each component, the LLM generates 3-5 specific diagnostic intents covering different angles:
- Current status and health metrics
- Configuration and settings
- Logs, events, or error records
- Connectivity and reachability information
- Resource utilization and performance

When `path_analysis.suggested_probes` or `missing_evidence` exist, they are injected as **priority intents** to fill topology evidence gaps.

### Step B: Semantic Search (per intent)
Each intent is searched individually in Qdrant's `tool_catalog` collection with tenant isolation. Results are merged and deduplicated to maximize tool diversity.

### Step C: Tool Selection & Argument Configuration
**System:** "You are an expert IT Systems Engineer. Select comprehensive diagnostic tools."

The LLM selects tools from the search results and configures arguments with:
- **Role-Based Sanitization**: Executor devices (firewalls, routers, servers, hypervisors, databases, etc.) get `device` argument. Targets (subnets, IPs, services, containers, VMs) get `target` argument.
- **Anti-Hallucination**: Missing mandatory params → skip tool.
- **Safety**: Read-only tools only.

### Step D: Brute Force Fallback
If Smart Selection yields no tools:
- Iterates all registered tools.
- Filters for read-only prefixes: `get`, `check`, `monitor`, `list`, `show`, `describe`, `fetch`.
- Matches vendor keyword if known.
- Selects general health/status/info/system/summary/overview tools.
- Limited to top 5 to prevent overload.

## Key Logic & Interactions
- **LLM Model:** Uses `LLM_MODEL_EVIDENCE_COLLECTOR` (e.g., `gpt-4.1-mini`) — optimized for tool calling speed.
- **Tool Governance**: Every tool checked against `CapabilityScope` allowlists and safety blocklists.
- **Adaptive Execution**: Tools executed via `AdaptiveExecutor` with self-healing on failures.
- **Evidence Storage**: Raw outputs saved to `EvidenceStore` (disk), references appended to state.
