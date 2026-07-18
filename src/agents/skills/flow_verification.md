# Skill: Control-Point Flow Verification (FortiGate)

## Purpose

Determine whether a firewall is affecting a **specific application flow** by verifying every interference mechanism against the flow's dependency profile — never by observing generic connectivity.

## How to Use This Skill

This skill is a **starting frame, not a rail**. The tool anchors below are verified against this platform's catalog:

- **Anchor names are pre-verified: pass them directly to `execute_tool`.** You do not need a `search_tool_catalog` hit to justify executing an anchor — search is discovery, not permission.
- Load this skill whenever a ticket asks whether a firewall or gateway is "blocking" something, an application fails for hosts behind it, or a flow works partially (some operations succeed, others do not).
- **Verdict contract**: "the firewall is not blocking X" is only valid after each interference mechanism relevant to X's dependency profile has been verified. Anything less must be reported as "not proven to affect X", listing exactly what was and was not verified.
- If evidence points outside the control point (logs, licensing, routing), follow it — load the corresponding domain skill or `load_domain_skill("lateral_thinking")` when the picture stops making sense.
- Routing note: the device selector parameter on every tool is `device` (the component id from the tenant inventory).

## Step 0 — Dependency Profile (mandatory before any tool call)

Write down the failing application's dependency profile: every flow it needs (destination endpoints/domains, protocol, port, direction), the resolution steps, and the order they are exercised. Sources: `search_knowledge_base`, vendor documentation, professional knowledge — state it explicitly as the model you will verify, and mark unverifiable items.

Example (mesh-VPN class: Tailscale, ZeroTier, Nebula): control/coordination channel over HTTPS to the vendor's endpoints; relay fallback (DERP/moon/lighthouse) over HTTPS or fixed ports; **direct peer path over a dedicated UDP port (e.g. UDP 41641) that requires NAT hole punching**; STUN for endpoint discovery; name resolution including the app's internal DNS (e.g. MagicDNS at 100.100.100.100). Working web browsing verifies none of these except generic 443 egress.

## The Interference Model (mental map)

A FortiGate can affect a flow through **independent mechanisms**. Verify each one relevant to the dependency profile; passing one never clears the others.

| # | Mechanism | How it breaks a flow while others work |
|---|---|---|
| 1 | Policy match / implicit deny | A specific port/proto (e.g. the app's UDP port) hits implicit deny while TCP/443 passes |
| 2 | UTM profiles on the matched policy | Policy allows, but app control / webfilter / dnsfilter / SSL deep inspection / IPS blocks the payload mid-stream |
| 3 | NAT behavior | Fixed-port vs. dynamic SNAT, pool type, central SNAT — hard NAT breaks UDP hole punching, degrading P2P apps to relays or failure |
| 4 | Routing / SD-WAN path | The dependency egresses an unexpected interface/WAN with different policy/NAT treatment |
| 5 | Shaping / policing | Flow passes but is degraded (shaper drops, bandwidth caps) |
| 6 | Local-in policy | Traffic addressed to the firewall itself (DNS proxy, VPN termination) is blocked |
| 7 | DoS policy | Bursty or highly parallel flows are rate-dropped |

## Verified Evidence Anchors (read-only)

| Tool | What it answers |
|---|---|
| `fgt_monitor_fw_get_firewall_policy_lookup` | **The discriminating test.** Simulates a packet (source interface/IP, protocol, destination, destination port per its args_schema) and returns the policy that would match — run it once per dependency in the profile, including the ones with no observed sessions. |
| `fgt_monitor_fw_get_firewall_sessions` | Live session table with filters (source/destination address, port, protocol, policyid). Attribution: filter by the profile's destination port/IPs — never attribute sessions by resemblance. |
| `fgt_cmdb_fw_ipmacbinding_setting_get_firewall_policy` / `..._policy_policyid` | Policy **configuration**: attached UTM profiles, NAT mode, ippool, log setting. **Misleading prefix**: firewall config tools live under `fgt_cmdb_fw_ipmacbinding_setting_*` — do not infer capability from names. |
| `fgt_monitor_fw_get_firewall_policy` | Per-policy runtime hit/byte counters. |
| `fgt_cmdb_app_custom_get_application_list` / `..._list_name` | Application-control profiles: blocked/monitored application signatures and categories. |
| `fgt_cmdb_web_content_get_webfilter_profile` / `..._profile_name` | Webfilter profiles attached to the policy. |
| `fgt_cmdb_dns_domain_filter_get_dnsfilter_profile` / `..._profile_name` | DNS-filter profiles — can silently break an application's name resolution. |
| `fgt_cmdb_fw_ipmacbinding_setting_get_firewall_ssl_ssh_profile` / `..._profile_name` | SSL/SSH inspection profiles — deep inspection breaks certificate-pinned apps. |
| `fgt_cmdb_ips_custom_get_sensor` / `..._sensor_name` | IPS sensors attached to the policy. |
| `fgt_cmdb_fw_ipmacbinding_setting_get_firewall_ippool` / `..._ippool_name`, `fgt_monitor_fw_get_firewall_ippool` | NAT pool config and usage — pool type decides port preservation, which decides hole punching. |
| `fgt_cmdb_fw_ipmacbinding_setting_get_firewall_central_snat_map`, `fgt_monitor_fw_get_firewall_central_snat_map` | Central SNAT rules that may override policy NAT. |
| `fgt_monitor_router_get_lookup` | Route lookup for a destination → actual egress interface. |
| `fgt_cmdb_fw_ipmacbinding_setting_get_firewall_local_in_policy` | Local-in policies (traffic to the firewall itself). |
| `fgt_cmdb_fw_ipmacbinding_setting_get_firewall_DoS_policy` | DoS policies. |
| `fgt_cmdb_fw_ipmacbinding_setting_get_firewall_shaping_policy`, `..._get_firewall_shaper_traffic_shaper` | Shaping policies and traffic shapers. |

Denied-traffic evidence (`action==deny` log entries, including local disk/memory fallback when FortiAnalyzer/FortiCloud fail): `load_domain_skill("logs")`.

Catalog queries that rank these tools (calibrated against this index):

- `"which firewall policy matches a packet source destination port"` → policy lookup
- `"active firewall sessions filtered by source and destination"` → session table
- `"firewall policy configuration NAT security profiles"` → policy config
- `"application control profile blocked applications"` → app control

## Investigation Sequence (starting frame)

1. **Dependency profile first (Step 0).** No verdict-bearing tool call before it exists.
2. **Per dependency, run `fgt_monitor_fw_get_firewall_policy_lookup`** with that dependency's tuple. An implicit-deny result for a required dependency is a root-cause finding; an allow result names the policy to inspect next.
3. **For each matched policy, get its configuration** (`..._get_firewall_policy_policyid`): attached UTM profiles, NAT mode, ippool, log setting. Session-table matches alone say nothing about UTM verdicts.
4. **Inspect each attached UTM profile** (app control, webfilter, dnsfilter, ssl-ssh, IPS anchors above): can it plausibly act on this application?
5. **Attribution pass**: `fgt_monitor_fw_get_firewall_sessions` filtered by the profile's destination ports/IPs. Presence and absence are both findings — a missing session for a required dependency localizes the failure at or before the client-to-firewall segment.
6. **Deny evidence**: `load_domain_skill("logs")` → traffic logs filtered `srcip==<host>` and `action==deny`, with local fallback on remote-backend errors.
7. **NAT sensitivity**: if the app needs inbound or hole-punched UDP, verify policy NAT mode, ippool type, and central SNAT.
8. **Classify every dependency**: `verified-pass` / `verified-fail` / `unverifiable from this vantage point` — then write the verdict scoped to that table (base methodology step 11).

Skip steps the evidence has already answered. Add steps this frame does not list if the dependency profile demands them.

## Safety Rail — tools you must NOT execute

The same tool families contain mutating members: `fgt_monitor_fw_post_firewall_session_close` / `..._close_all` / `..._close_multiple`, `fgt_monitor_fw_post_firewall_policy_reset`, `..._policy_clear_counters`, `..._central_snat_map_reset` / `..._clear_counters`. Never execute them. If resolution requires a configuration change (new policy, profile exemption, NAT change), put it in the recommended plan with its impact and set `case_status` to `needs_human`.

## Common Pitfalls

- **Generic connectivity is not the flow.** Working TCP/443 egress proves nothing about the app's UDP port, STUN, or its internal DNS.
- **Compatibility is not attribution.** Sessions to CDN-looking IPs on port 443 are compatible with half the internet; attribute only via the dependency profile's known endpoints, FQDNs, or log fields.
- **Session presence ≠ UTM pass.** A session can be established and the payload still blocked mid-stream by app control, IPS, or SSL inspection.
- **The absent session is a positive finding.** If a required dependency shows no session at all, the failure is at or before the firewall — say so instead of ignoring it.
- **All mechanisms pass ≠ "host problem confirmed".** The correct claim is: every verified mechanism passes; the failure point is outside this vantage point; then list the minimal missing evidence (e.g. host-side client status, upstream provider state).

## Reporting

Present a per-dependency verdict table, then follow the base Output Contract for the ticket mode:

| Dependency (proto/port/destination) | Policy matched | UTM profiles checked | NAT effect | Sessions attributed | Deny logs | Verdict |
|---|---|---|---|---|---|---|

The overall claim must match the table: any `unverifiable` row forbids "the firewall is not the cause" — the correct claim is "not proven to affect the flow", listing the unverified mechanisms and the minimal missing evidence.
