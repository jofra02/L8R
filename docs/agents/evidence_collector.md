# Evidence Collector Agent

## Description
The Evidence Collector Agent gathers the initial diagnostic evidence about the environment. It uses a **multi-intent approach**: the LLM generates 1-3 short keyword-style search queries per component, each searched independently via Qdrant semantic search for tool catalog matching. When topology/path analysis exists, it prioritizes filling identified evidence gaps.

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

### Step A: Keyword Intent Generation
**System:** "You are a tool-search specialist. Output short keyword queries for finding IT diagnostic tools."

For each component, the LLM generates 1-3 SHORT keyword-style search queries (2-6 words) optimized for semantic similarity against tool descriptions. Cross-device context is provided so the LLM understands the full scenario.

**Rules:**
- Each query is 2-6 words — like a search engine query, NOT a sentence.
- Include vendor or technology name when known (e.g., "fortigate", "vcenter", "cisco").
- Focus on the CATEGORY of tool needed (routing, policy, interface, performance, logs, database, deployment, container, api, authentication, storage, backup, etc.).
- No IPs, subnets, or ticket-specific details — those go into tool arguments, not search.
- **Configuration-first**: Prefer tools that read existing configuration over live traffic tools.

When `path_analysis.suggested_probes` or `missing_evidence` exist, they are injected as priority context.

### Step B: Semantic Search (per intent)
Each intent is searched individually in Qdrant's `tool_catalog` collection with tenant isolation. Results are merged and deduplicated to maximize tool diversity.

### Step C: Tool Selection & Argument Configuration
**System:** "You are an expert IT Systems Engineer. Select comprehensive diagnostic tools."

The LLM selects tools from the search results and configures arguments with:
- **Role-Based Sanitization**: Executor devices (firewalls, routers, servers, hypervisors, databases, etc.) get `device` argument. Targets (subnets, IPs, services, containers, VMs) get `target` argument.
- **Placeholder Injection**: Arguments are only auto-injected when the LLM left placeholder values (`<device>`, `DEVICE`, `""`).
- **Anti-Hallucination**: Missing mandatory params -> skip tool.
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
- **Adaptive Execution**: Tools executed via `AdaptiveExecutor` with self-healing on failures. `customer_id` is passed for tenant-scoped learning.
- **Evidence Storage**: Raw outputs saved to `EvidenceStore` (disk, namespaced by `customer_id`), references appended to state.
- **Configuration-First Principle**: Prefers tools that inspect existing configuration (routes, policies, rules, definitions) over live traffic tools (debug flows, captures, sniffers, sessions).
