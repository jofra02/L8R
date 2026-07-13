# Skill: FortiGate Licensing Verification

## Purpose

Verify the licensing and entitlement state of a FortiGate: what the device is entitled to, what is actually active, when each entitlement expires, and whether the update-delivery path that keeps entitlements useful is healthy.

## How to Use This Skill

This skill is a **starting frame, not a rail**. The tool anchors below are verified against this platform's catalog, but the catalog evolves and every environment differs:

- **Anchor names are pre-verified: pass them directly to `execute_tool`.** You do not need a `search_tool_catalog` hit to justify executing an anchor — search is discovery, not permission. If a search does not surface an anchor, the anchor still exists.
- Use `search_tool_catalog` for anything **beyond** the anchors, or to find better matches for needs this skill does not cover.
- If evidence points outside licensing (time, DNS, routing, outbound policy), follow it. Load other domain skills or `load_domain_skill("lateral_thinking")` when the picture stops making sense.
- Nothing here forbids a lateral search. The only hard limits are the platform rules: read-only, evidence-only, configuration-first.
- Routing note: the device selector parameter on every tool is `device` (the component id from the tenant inventory).

## The FortiGate Licensing Model (mental map)

Licensing on a FortiGate is not one flag — it is six distinct layers. A ticket that says "license problem" can live in any of them:

1. **Device identity and registration** — serial number, model, firmware; whether the device is registered to a FortiCare account.
2. **Support contracts (FortiCare)** — hardware and firmware support entitlements with expiry dates. These gate TAC support and firmware upgrades, not security features.
3. **FortiGuard security subscriptions** — per-service entitlements, each with its own status, expiry, and locally installed definition/engine version: AntiVirus, IPS + Application Control, Web Filtering, Anti-Spam, Outbreak Prevention, Security Rating, IoT/OT detection, Industrial DB.
4. **Update delivery path** — the channel that turns an entitlement into current protections: FortiGuard server reachability (or a FortiManager override server), update schedule, protocol/port/anycast settings. **A valid entitlement with stale definitions is a delivery problem, not a licensing problem.**
5. **Platform capacity licenses** — VM licenses (CPU/RAM tier, Flex-VM, evaluation), VDOM licenses, Hyperscale. These gate capacity and features of the platform itself.
6. **Cloud and Fabric service entitlements** — FortiAnalyzer license state, FortiCloud logging, FortiToken Cloud, EMS/endpoint integrations.

Classify which layers the ticket actually touches before executing anything.

## Verified Evidence Anchors (read-only)

Tool names verified in this platform's indexed catalog. Search for them by function; example queries that rank them well are given below.

| Tool | What it answers |
|---|---|
| `fgt_monitor_lic_get_license_status` | **Primary snapshot — answers most licensing AND definition-version questions in one call.** Per service (IPS, AV, app control, web filtering, industrial DB, malware DBs, security rating, ...): entitlement status, expiry, **installed signature/engine `version`, `last_update`, `last_update_attempt`, `last_update_result_status`**; plus FortiCare registration/contract and VM license. If the ticket asks for IPS/AV versions or update timestamps, execute this first. |
| `fgt_monitor_sys_get_status` | Serial, model, firmware version, hostname — and the device clock context needed to trust expiry evaluations. |
| `fgt_monitor_sys_get_fortiguard_server_info` | FortiGuard server list and per-server state — is the update path alive, which server is used. |
| `fgt_monitor_net_get_network_fortiguard_live_services_latency` | Live FortiGuard service reachability/latency — distinguishes "entitled but unreachable" from "not entitled". |
| `fgt_cmdb_sys_get_fortiguard` | FortiGuard service **configuration**: update source/override (FortiManager?), protocol, port, anycast, schedule. |
| `fgt_cmdb_fguard_get_fortiguard_service_communication_stats` | Historical FortiGuard communication stats — when did updates last succeed. `service_type` and `timeslot` are **optional**: if a call errors, retry with only `device`. |
| `fgt_cmdb_registration_get_forticloud_device_status` | FortiCloud registration state of the device. |
| `fgt_monitor_lic_get_license_fortianalyzer_status` | License/registration of the connected FortiAnalyzer (fabric logging entitlement). |
| `fgt_monitor_sys_get_vdom_resource` / `fgt_cmdb_sys_get_vdom` | VDOM count and resources — context for VDOM/VM capacity licenses. |
| `fgt_cmdb_log_disk_filter_get_log_fortiguard_setting` | FortiCloud logging configuration — is a cloud logging entitlement actually in use. |
| `fgt_monitor_web_get_webfilter_fortiguard_categories` | **Functional probe**: fetching live category data exercises the Web Filter entitlement end to end. |

Catalog queries that rank the right tools highly (calibrated against this index):

- `"license registration status support contract expiration"` → license status tools
- `"FortiGuard server connectivity update service reachability"` → delivery-path tools
- `"FortiGuard services configuration update source"` → FortiGuard config
- `"VDOM resource usage"` → capacity context

## Investigation Sequence (starting frame)

1. **Authoritative snapshot first.** `fgt_monitor_lic_get_license_status` plus `fgt_monitor_sys_get_status`. One call answers most licensing questions; the second anchors serial/firmware/clock.
2. **Interpret per service** (see next section). Build the verdict table before collecting more.
3. **Corroborate the delivery path only if something looks stale, pending, or contradictory** — server info, live-services latency, FortiGuard config (check for an override/FortiManager source), communication stats.
4. **Platform capacity** only when the ticket involves VM/VDOM/Hyperscale: VDOM resource + VDOM config against the entitled limits reported in the license snapshot.
5. **Functional probes and fabric services** when entitlement state and observed behavior disagree (e.g. web filter category fetch, FortiAnalyzer status).

Skip steps that the evidence has already answered. Add steps the frame does not list if the evidence demands it.

## Interpreting the License Snapshot

- The snapshot is organized **per service**, keyed by service name (`ips`, `antivirus`, `appctrl`, `web_filtering`, `forticare`, `internet_service_db`, `ai_malware_detection`, ...). Entries carry a `type` that tells you how to read them:
  - `downloaded_fds_object` — a definition/signature package: `status`, `version`, `expires`, `last_update`, `last_update_attempt`, `last_update_result_status` (e.g. `update_result_success`, `update_result_not_authorized`), `entitlement` code.
  - `live_fortiguard_service` — a query-time cloud service (web filtering, anti-spam, outbreak prevention): `status`, `expires`, no local version to report.
  - `cloud_service_status` / `live_cloud_service` — FortiCare/FortiCloud/FortiGuard connection and cloud entitlements; `fortiguard` here carries `connected`, `last_connection_success`, `next_scheduled_update`.
- `last_update_result_status: update_result_not_authorized` on a `downloaded_fds_object` means the device tried to update but the entitlement no longer authorizes it — the definitive signature that **expiry is blocking updates** (definitions freeze at their last version).
- Expiry and update fields are epoch seconds — convert before reporting.
- Verdict matrix:
  - **Entitled + current definitions** → healthy.
  - **Entitled + stale definitions** → delivery problem (path, schedule, override source), not a licensing problem.
  - **Expired** → licensing problem; note the grace behavior: features often keep running with the last downloaded definitions, silently aging.
  - **Pending / unregistered** → registration or first-contact problem; check FortiCare registration and FortiGuard reachability before concluding.
- **Clock skew invalidates everything**: expiry is evaluated against the device clock. Verify system time (from `fgt_monitor_sys_get_status`) before reporting a surprising expiration.
- Some services are free (e.g. basic DDNS, certain category fetches); absence of a paid entitlement is not automatically a finding.

## Safety Rail — tools you must NOT execute

The catalog also indexes **mutating** licensing tools. They are outside the read-only mandate and some are outright destructive:

- `fgt_monitor_sys_post_vmlicense_download` / `_download_eval` / `_upload` — **reboot the device immediately** on success
- `fgt_monitor_sys_post_fortiguard_update` / `_manual_update` / `_test_availability` / `_clear_statistics`
- `fgt_cmdb_registration_post_forticare_*` (login, create, transfer, deregister, add_license)
- `fgt_monitor_lic_post_license_database_upgrade`
- `fgt_cmdb_sys_put_fortiguard`, `fgt_cmdb_log_disk_filter_put_log_fortiguard_*`

If resolution requires any of these, put the action in the recommended plan with its risk (device reboot, account mutation) and set `case_status` to `needs_human`. Never execute them.

## Common Pitfalls

- **"FortiGuard unreachable" ≠ "license expired"** — separate entitlement state from delivery state in every conclusion.
- **FortiManager as update source**: in managed or air-gapped environments `fgt_cmdb_sys_get_fortiguard` shows an override server; direct FortiGuard unreachability is then expected, not a fault.
- **Egress dependencies**: FortiGuard updates depend on DNS resolution and outbound reachability (typically 443/8888) from the management VDOM — a "licensing" ticket can be an egress policy or DNS ticket in disguise.
- **Evaluation/Flex VM licenses** carry capacity limits (CPU/RAM) and short validity — a "performance" complaint on a VM can be a license-tier fact.
- **Web Filtering is live-rated**: an expired Web Filter entitlement breaks category lookups at request time even though all configuration looks intact.
- **VDOM scope**: entitlements are global, but several monitors are VDOM-scoped — query with global scope when the parameter exists.

## Reporting

Present the licensing verdict as a Markdown table, then follow the base Output Contract for the ticket mode:

| Service | Entitlement | Expires | Local version / last update | Verdict |
|---|---|---|---|---|

State explicitly which layer of the model the root cause lives in (entitlement, delivery, capacity, registration, or clock), and what was ruled out.
