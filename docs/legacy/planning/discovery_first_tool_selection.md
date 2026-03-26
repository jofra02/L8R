# Task: Discovery-First Tool Selection Strategy

## Problem

The current ToolSelector pipeline finds relevant tools but discards many of them because it can't bind their required arguments. The required values (host names, interface IDs, tunnel names, policy IDs, etc.) aren't in the agent's context yet — they need to be **discovered first** by running broader, exploratory tools.

### Example of current (broken) flow

```
Ticket: "Tengo caído un nodo/host del vCenter"

1. Agent searches for tools → finds `get_host_status(host_id=REQUIRED)`
2. Agent doesn't know the host_id (it's not in the ticket, not in context)
3. Tool gets discarded because host_id can't be bound
4. Agent has no tools to work with, or works with inferior alternatives
```

### What should happen instead

```
Ticket: "Tengo caído un nodo/host del vCenter"

1. Agent recognizes it needs environmental context first
2. Agent prioritizes discovery tools:
   - `list_vcenter_hosts()` → returns all hosts with IDs and status
   - `get_vcenter_summary()` → returns cluster overview
3. Now the agent has host IDs, names, and status in context
4. Agent identifies which host is down from the listing
5. NOW agent can bind and execute `get_host_status(host_id="esxi-node-03")`
6. Agent continues with specific diagnostic tools using discovered values
```

## Core Concept: Two-Phase Tool Selection

The fundamental shift is: **don't go straight to the specific diagnostic tool. First, discover what exists, then drill down.**

This applies across ALL IT domains:

### Pattern: List/Discover → then Get/Inspect

| Domain | Discovery tool (no specific args) | Specific tool (needs discovered args) |
|---|---|---|
| Virtualization | `list_hosts`, `get_cluster_summary` | `get_host_status(host_id)`, `get_vm_details(vm_name)` |
| Networking | `list_interfaces`, `show_route_table` | `get_interface_detail(interface_name)`, `get_route(prefix)` |
| Firewall | `list_policies`, `list_zones` | `get_policy_detail(policy_id)`, `get_zone_config(zone_name)` |
| VPN | `list_vpn_tunnels`, `list_ipsec_sas` | `get_tunnel_status(tunnel_id)`, `get_sa_detail(sa_id)` |
| Storage | `list_volumes`, `list_luns` | `get_volume_detail(vol_id)`, `get_lun_status(lun_id)` |
| SD-WAN | `list_wan_links`, `list_overlay_tunnels` | `get_link_stats(link_id)`, `get_tunnel_health(tunnel_name)` |
| Load Balancer | `list_virtual_servers`, `list_pools` | `get_vs_status(vs_name)`, `get_pool_members(pool_id)` |
| HCI | `list_cluster_nodes`, `get_cluster_health` | `get_node_detail(node_id)`, `get_disk_group(dg_id)` |
| DNS | `list_zones`, `get_dns_summary` | `get_zone_records(zone_name)`, `get_record(fqdn)` |
| Containers | `list_pods`, `list_namespaces` | `get_pod_logs(pod_name)`, `get_deployment(deploy_name)` |
| Users/Auth | `list_users`, `list_auth_servers` | `get_user_detail(username)`, `get_server_status(server_id)` |
| Certificates | `list_certificates` | `get_cert_detail(cert_id)`, `check_cert_expiry(cert_name)` |
| Backup | `list_backup_jobs`, `list_repositories` | `get_job_status(job_id)`, `get_repo_health(repo_name)` |
| Database | `list_instances`, `list_databases` | `get_instance_health(instance_id)`, `get_db_stats(db_name)` |

The pattern is universal: **every IT domain has "list/summary/overview" tools that return inventories and identifiers, and "get/detail/inspect" tools that need those identifiers as input.**

## Implementation

### Approach: Tool Classification by Specificity

Classify each tool into one of two tiers based on its argument requirements:

- **Tier 1 — Discovery/Context tools:** Tools that require zero specific identifiers OR only require a broad scope parameter (like a device/component ID that's already known from the ticket). These tools LIST, SUMMARIZE, or give OVERVIEW data. They return inventories, enumerations, and status summaries. Their output typically contains the identifiers needed by Tier 2 tools.

- **Tier 2 — Specific/Diagnostic tools:** Tools that require one or more specific identifiers (host_id, interface_name, policy_id, tunnel_name, etc.) that can only be known after running a Tier 1 tool or from prior context. These tools GET DETAIL, INSPECT, or CONFIGURE specific resources.

### Classification Heuristics — Use ALL Available MCP Metadata

MCP tools expose rich metadata beyond just the name. The tier classification MUST analyze all available signals holistically — name alone is not reliable. A tool called `get_interfaces` could be a discovery tool (lists all interfaces) or a specific tool (gets interfaces matching a filter). The metadata tells you which.

**Available MCP tool metadata to analyze:**

1. **Tool name** — useful as a weak signal, not definitive
2. **Tool description** — often the richest signal; describes what the tool does and returns in natural language
3. **Input schema (`inputSchema`)** — JSON Schema defining parameters:
   - `properties` — each parameter with its name, type, and description
   - `required` — which parameters are mandatory vs optional
   - Parameter descriptions — often say things like "the ID of the host to query" (Tier 2 signal) or "optional filter" (Tier 1 signal)
   - Parameter types and enums — constrained values vs free-form identifiers
4. **Return/output schema** (if available) — whether it returns a list of items or a single resource detail
5. **Annotations/hints** (MCP extensions) — some servers include custom metadata like `readOnly`, `idempotent`, `destructive`, etc.

**Tier 1 (discovery) — signals across ALL metadata fields:**

| Metadata field | Tier 1 signal |
|---|---|
| **Name** | Patterns like `list_*`, `get_all_*`, `show_*s` (plural), `*_summary`, `*_overview`, `*_inventory` — weak signal, use as tiebreaker only |
| **Description** | Contains phrases like: "lists all", "returns all", "enumerates", "shows summary/overview", "retrieves inventory", "gets current state of all", "returns a list of", "shows the configuration overview" |
| **Required params** | Has ZERO required params, OR only requires broad scope identifiers that are typically known from the ticket/component (e.g., `device_ip`, `vcenter_host`, `cluster_name`) — NOT resource-specific IDs |
| **Param descriptions** | Required params described as scope/connection targets: "IP of the device", "hostname of the vCenter", "name of the cluster to query". These are component-level identifiers, not resource-specific ones |
| **Optional params** | May have optional filters like `status_filter`, `limit`, `name_pattern` — but they're optional, the tool works without them |
| **Param types** | Scope params tend to be connection-level (IPs, hostnames, base URLs) rather than resource-level (IDs, specific names) |
| **Return schema** | Returns an array/list type, or description mentions "returns a list of", "returns all matching" |
| **Annotations** | Marked as `readOnly: true`, `idempotent: true` — discovery tools don't modify state |

**Tier 2 (specific) — signals across ALL metadata fields:**

| Metadata field | Tier 2 signal |
|---|---|
| **Name** | Patterns like `get_*_detail`, `get_*_status`, `check_*`, `inspect_*`, `configure_*`, `update_*` — weak signal |
| **Description** | Contains phrases like: "returns details for a specific", "gets the status of", "retrieves configuration of", "inspects the", "shows detail for the given", "checks health of" |
| **Required params** | Has one or more required params that represent specific resource identifiers — these are values that come from WITHIN an infrastructure, not from the ticket itself |
| **Param descriptions** | Required params described as resource-specific: "the host ID", "name of the interface", "policy ID to inspect", "tunnel name to check", "VM identifier". The key signal is that these values need to be DISCOVERED, not already known |
| **Param types** | Resource identifier params — strings or integers that reference a specific instance of something (a specific host, a specific policy, a specific interface) |
| **Return schema** | Returns a single object, or description mentions "returns details for", "returns the configuration of" |
| **Annotations** | May or may not be `readOnly` — Tier 2 includes both read and write operations on specific resources |

**The critical distinction is in the REQUIRED PARAMETERS and their descriptions:**

```
Tier 1 required param example:
  "device_ip": {
    "type": "string",
    "description": "IP address of the FortiGate device to connect to"
  }
  → This is a CONNECTION/SCOPE param — the agent knows this from the component/ticket

Tier 2 required param example:
  "policy_id": {
    "type": "integer",
    "description": "The ID of the firewall policy to retrieve"
  }
  → This is a RESOURCE IDENTIFIER — the agent needs to DISCOVER this value first

Tier 2 required param example:
  "interface_name": {
    "type": "string",
    "description": "Name of the network interface (e.g., port1, wan1)"
  }
  → This is a RESOURCE IDENTIFIER — needs prior knowledge of what interfaces exist
```

**Ambiguous cases — use multiple signals together:**

Some tools sit in a gray area. Use the combination of signals to decide:

```
Tool: get_interfaces
  Description: "Get all interfaces for a device"
  Required: {"device_ip": "IP of the device"}
  → Only requires a scope param, description says "all" → Tier 1

Tool: get_interface
  Description: "Get detailed information about a specific interface"
  Required: {"device_ip": "IP of the device", "interface_name": "Name of the interface"}
  → Requires a resource identifier (interface_name) → Tier 2

Tool: get_host_vms
  Description: "List all VMs running on a specific ESXi host"
  Required: {"host_id": "The ESXi host identifier"}
  → Despite "list all", requires a host_id that needs discovery → Tier 2
  → BUT it's a Tier 2 that ALSO acts as discovery (outputs VM identifiers)
  → Tag as: tier=2, provides_discovery_for=[vm_name, vm_id]
```

This last case is important: **some Tier 2 tools also produce discovery data for deeper levels.** The tier system isn't strictly binary — it's a dependency chain. `list_hosts` (Tier 1) → `get_host_vms(host_id)` (Tier 2, but discovers VM IDs) → `get_vm_detail(vm_id)` (Tier 2). The classification should capture this by noting what identifiers each tool's output PROVIDES, not just what it REQUIRES.

### Where to Add This Classification

Store the tier as metadata on the tool record alongside the category tags (from the category system). Fields to store:

- `tier`: 1 or 2
- `requires_identifiers`: list of parameter names that are resource-specific (need discovery). Empty for Tier 1
- `provides_identifiers`: list of identifier types this tool's output makes available (e.g., `["host_id", "host_name", "host_status"]`). This enables building the discovery chain automatically
- `scope_params`: list of parameter names that are connection/scope level (device_ip, vcenter_host, etc.)

Classification can be:
- **Inferred at registration time** by analyzing the full MCP tool schema (name + description + inputSchema properties + required array + param descriptions + return schema)
- **LLM-assisted** at registration time — pass the complete tool schema to the LLM and ask it to classify tier + identify which params are scope vs resource-identifier
- **Manually overridden** via a field in the tool definition or a config mapping file

### Changes to ToolSelector Flow

Modify the tool selection and execution pipeline to implement a discovery-first strategy:

#### Step 1: Assess Available Context

Before searching for tools, evaluate what identifiers/values the agent already has in context:
- From the ticket/request text (user may have mentioned specific names)
- From `context.facts` (prior tool executions may have populated values)
- From component metadata (device name, IP, type are usually known)

#### Step 2: Prioritize Tool Tier Based on Context Gaps

When selecting tools:

```
IF the agent has enough context to bind specific tools (identifiers are known):
    → Select and bind Tier 2 tools directly (current behavior, no change needed)

ELSE IF the agent lacks specific identifiers needed by relevant Tier 2 tools:
    → Prioritize Tier 1 (discovery) tools for the same domain/category
    → Execute discovery tools FIRST
    → Feed their output into context.facts
    → THEN re-evaluate and select Tier 2 tools with newly available identifiers
```

#### Step 3: Discovery-to-Specific Tool Linking

Build the dependency chain between tools automatically using the `provides_identifiers` and `requires_identifiers` metadata from classification:

```
Tool: list_vcenter_hosts
  provides_identifiers: [host_id, host_name, host_status, cluster_name]
  
Tool: get_host_status
  requires_identifiers: [host_id]

→ Automatic link: list_vcenter_hosts ENABLES get_host_status
   because provides_identifiers contains what requires_identifiers needs
```

This linking should be built **automatically at registration time** by cross-referencing all tools:

```
for each Tier 2 tool:
    for each identifier in requires_identifiers:
        find all tools where provides_identifiers contains that identifier
        → those are the potential discovery prerequisites
```

The matching should be smart about it — not just exact string match on param names, but semantic matching using the parameter descriptions from the MCP schema. For example:
- A tool that provides `host_id` should match a tool that requires `esxi_host_id` or `hostIdentifier`
- Use the param descriptions to confirm: "The ESXi host identifier" ↔ "ID of the host returned by list commands"

This can be:
- **Automatic** — cross-reference `provides_identifiers` ↔ `requires_identifiers` across all registered tools (preferred — scales without manual work)
- **LLM-assisted** — when automatic matching is ambiguous, use the LLM to evaluate whether two param descriptions refer to the same concept
- **Manually supplemented** — for edge cases where automatic matching fails, allow explicit overrides in tool config

#### Step 4: Execution Ordering

When the agent's plan includes both Tier 1 and Tier 2 tools:

1. Execute all selected Tier 1 (discovery) tools first
2. Parse their output and extract identifiers into `context.facts`
3. Re-run binding for Tier 2 tools using the enriched context
4. Execute Tier 2 tools with now-bound arguments

This may already partially exist in the prerequisite resolution system. If so, the change is to make discovery tools the PREFERRED prereq strategy rather than a last resort.

### Integration with Existing Systems

#### Interaction with Prerequisite Resolution

The current prereq resolution tries to find a tool that provides missing parameter values. This discovery-first strategy is essentially the same concept but applied PROACTIVELY instead of reactively:

- **Current (reactive):** Select specific tool → can't bind → trigger prereq resolution → maybe find a discovery tool → maybe resolve
- **Proposed (proactive):** Recognize context gaps upfront → select discovery tools first → enrich context → then select specific tools with full binding

Consider whether to:
- (A) Enhance the existing prereq resolution to prefer discovery/list tools, OR
- (B) Add a new pre-phase before tool selection that handles discovery, OR
- (C) Modify the tool scoring/ranking to boost Tier 1 tools when context is sparse

Option (A) is probably the least invasive. Option (B) gives more control. Evaluate based on current architecture.

#### Interaction with Category System

The category tags and the tier classification work together:
- Category tells you WHAT domain the tool operates in (routing, firewall, hypervisor...)
- Tier tells you WHETHER the tool discovers context or needs context

Search flow becomes:
1. Infer category from intent → filter by category
2. Within that category, check if we have enough context for Tier 2 tools
3. If not, prioritize Tier 1 tools from that category first
4. After Tier 1 execution, select Tier 2 tools with enriched context

#### Interaction with Facts/Context

Discovery tool output needs to flow into `context.facts` reliably. Ensure that:
- Tier 1 tool output is parsed and key identifiers are extracted as facts
- Fact keys are named consistently so the binding LLM can match them to parameter names
- Facts from discovery tools are available for the SAME selection cycle (not just the next ticket iteration)

### Example: Full Flow After Changes

```
Ticket: "Tengo caído un nodo/host del vCenter"
Component: vcenter-prod-01

Phase 1 — Context Assessment:
  - Known: component = vcenter-prod-01, type = vcenter
  - Missing: which host is down (no host_id, no host_name)
  - Category inferred: hypervisor, virtual_machines, status_health

Phase 2 — Discovery Tool Selection:
  - Finds Tier 1 tools in [hypervisor, status_health] category:
    → list_vcenter_hosts(vcenter=vcenter-prod-01)  ← only needs component, which we have
    → get_cluster_summary(vcenter=vcenter-prod-01)
  - Executes discovery tools
  - Output: [
      {host_id: "esxi-01", name: "esxi-node-01", status: "connected"},
      {host_id: "esxi-02", name: "esxi-node-02", status: "connected"},
      {host_id: "esxi-03", name: "esxi-node-03", status: "disconnected"},  ← the down host
    ]
  - Extracts facts: target_host_id=esxi-03, target_host_name=esxi-node-03

Phase 3 — Specific Tool Selection:
  - Now searches for Tier 2 tools with enriched context
  - Finds and CAN NOW BIND:
    → get_host_status(host_id="esxi-03")
    → get_host_hardware_health(host_id="esxi-03")
    → get_host_vmlist(host_id="esxi-03")  ← to know which VMs are affected
  - Executes specific diagnostic tools
  - Agent now has full picture for diagnosis
```

## Implementation Notes

- Start by reading the current tool selection, binding, and prereq resolution flow in `tool_selector.py`
- The tier classification should be stored alongside category tags in the tool metadata
- Evaluate whether this is best implemented as an enhancement to prereq resolution or as a new pre-phase
- The discovery-first pattern should NOT add latency when context is already sufficient — if the agent already has the identifiers it needs, skip straight to Tier 2
- Log the discovery phase clearly: which Tier 1 tools ran, what identifiers were extracted, which Tier 2 tools were subsequently enabled
- This change should dramatically reduce the number of tools discarded for unbindable parameters, because the values will be discovered proactively instead of hoped for