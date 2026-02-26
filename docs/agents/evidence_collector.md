# Evidence Collector Agent

## Description
The Evidence Collector Agent is responsible for gathering the initial set of facts about the environment. It uses a two-stage approach: "Smart Selection" (LLM-driven) and "Brute Force Fallback" (Heuristic-driven) to ensure that at least some baseline evidence is always collected.

## Role in Graph
- **Node Name:** `evidence_collector`
- **Upstream:** `supervisor` (typically when no evidence exists yet)
- **Downstream:** `enricher_agent` (to parse and analyze the raw outputs)

## Inputs
- `state["ticket"]`: Ticket text to understand the issue.
- `state["components"]`: List of identified components to target.
- `state["evidence_refs"]`: Existing evidence (it appends to this list).

## Outputs
- `state["evidence_refs"]`: List of new `EvidenceSnapshot` objects pointing to the collected data.

## Prompts

### 1. Keyword Generation (Smart Selection Step A)
**System:** "You are an expert Network Engineer."
**Goal:** Generate search keywords to find relevant tools in the registry.
**Prompt Structure:**
```text
Context:
Ticket: "{ticket_text}"
Component: {component_id} (Role: {role}). {vendor_context}

Task: Identify 3-5 specific keywords to search for diagnostic tools. 
Focus on the vendor/technology and the action.
CRITICAL: Include terms like 'monitor', 'status', 'health', 'check', 'get'.

Return ONLY a JSON list of strings.
```

### 2. Tool Selection (Smart Selection Step C)
**System:** "You are an expert Network Engineer. Select comprehensive diagnostic tools."
**Goal:** Select multiple tools from the search results.
**Prompt Structure:**
```text
Context:
Ticket: "{ticket_text}"
Component: {component_id} ...

Available Tools:
{tool_descriptions}

Task: Select ALL valuable tools to diagnose the issue.
Construct the arguments for each tool.

GUIDELINES:
1. CRITICAL: For tools requiring a 'device', 'target', 'host', or 'ip' argument, USE "{component_id}" as the value.
2. Analyze the Schema: Distinguish between Mandatory and Optional arguments.
3. ANTI-HALLUCINATION: Do NOT invent parameters. If an optional parameter is unknown, OMIT IT.
4. SPECIAL RULE FOR TARGETS: If this component is a Subnet/IP, DO NOT use it as the 'device'. Use it as 'target' or 'address'.

Return ONLY a JSON LIST of objects:
[ { "name": "...", "args": { ... } } ]
```

## Key Logic & Interactions

-   **LLM Model:** Uses `LLM_MODEL_EVIDENCE_COLLECTOR` (e.g., `gpt-4.1-mini`), which is specifically optimized for tool calling speed.

### 1. Smart Selection & Device Targeting
For each component:
1.  Asks LLM for keywords.
2.  Searches `CapabilityRegistry`.
3.  Asks LLM to select tools.
4.  **Role-Based Sanitization:**
    *   **Executors (Firewalls, Routers):** Component ID is injected as `device`.
    *   **Targets (Subnets, IPs):** Component ID is injected as `target`, `destination`, or `subnet`. It is NEVER used as `device` to prevent "Device NOT FOUND" errors.

### 2. Brute Force Fallback
If Smart Selection yields no tools (e.g., due to search failure or empty LLM response):
-   It iterates through **all** available tools in the registry.
-   Filters for "safe" read-only verbs (`get`, `check`, `monitor`, `list`, `show`).
-   Matches against the component's `vendor` and `role`.
-   **Fortinet Heuristic:** If vendor is Fortinet, it prioritizes `fgt_` tools containing "health", "status", "info", or "system".
-   **Universal Fallback:** Always considers `ping` if available.
-   Limits execution to the top 5 matches to prevent system overload.

### Evidence Storage
Like the Investigator, it saves raw outputs to the `EvidenceStore` and appends the reference snapshots to the global state.
