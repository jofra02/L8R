# Skill: Tool Catalog Search

## How the Catalog Works

Tools are indexed by their **description and parameter descriptions** as embedded text. When you call `search_tool_catalog`, your query is matched via semantic similarity against that text — not against the tool name.

**Search by what the tool DOES, not by what you think it's called.**

## Tool Naming Convention

Tools follow a vendor-prefixed pattern:

```
{vendor_prefix}_{subsystem}_{module}_{operation}_{resource}
```

Examples:
- `fgt74_monitor_fw_get_firewall_policy` — FortiGate, monitor subsystem, read, firewall policy runtime stats
- `fgt74_monitor_sys_get_status` — FortiGate, monitor subsystem, read, system status
- `fgt74_monitor_router_get_ipv4` — FortiGate, monitor subsystem, read, IPv4 routing table

You don't need to guess the name. The search matches on description content.

## What Each Tool Entry Contains

When `search_tool_catalog` returns results, each tool has:

- **tool_name**: The exact identifier you pass to `execute_tool`
- **description**: What the tool does and what data it returns
- **args_schema**: JSON schema — `properties` (parameter names + descriptions) and `required` (mandatory params)
- **vendor**: Lowercase vendor (e.g. `fortinet`, `cisco`, `vmware`)
- **categories**: Domain tags (e.g. `["firewall", "nat"]`, `["routing", "bgp_peering"]`)

## How to Write Effective Queries

Describe the **data you need** in natural language. Include domain context to disambiguate.

```
Good:
  "list all interfaces with operational status and IP addresses"
  "effective routing table with next-hop and outbound interface"
  "firewall policies with source destination service and action"
  "IPSEC tunnel operational status and phase2 selectors"
  "system resource usage CPU memory uptime"
  "BGP neighbor state and received prefix count"
  "DHCP lease table with assigned addresses"

Bad:
  "fgt74_get_interface"       — don't guess tool names
  "show ip route"           — don't use CLI syntax
  "get fortigate stuff"     — too vague
  "tunnel status"           — ambiguous without domain context
  "neighbor"                — could be ARP, BGP, OSPF, LLDP
```

Use multiple focused searches rather than one broad query. Each search returns up to 10 results.
