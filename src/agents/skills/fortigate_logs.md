# Skill: FortiGate Log Retrieval & Analysis

## Purpose

Retrieve and analyze historical logs from a FortiGate — traffic, web browsing, security events — by selecting the log storage backend that actually holds data, and diagnose why an expected log does not exist.

## How to Use This Skill

This skill is a **starting frame, not a rail**. The tool anchors below are verified against this platform's catalog, but the catalog evolves and every environment differs:

- **Anchor names are pre-verified: pass them directly to `execute_tool`.** You do not need a `search_tool_catalog` hit to justify executing an anchor — search is discovery, not permission. If a search does not surface an anchor, the anchor still exists.
- **Local log retrieval tool names do not contain the word "log"** (`fgt_cmdb_disk_get_*` retrieves from `/api/v2/log/disk/...`). Never conclude from tool names or search misses that local log retrieval does not exist.
- Load this skill whenever a ticket involves reconstructing past activity (browsing, connections, events, detections) — and especially when a remote log source (FortiAnalyzer, FortiCloud, syslog collector) fails or reports disabled.
- If evidence points outside logging (policy, routing, entitlements), follow it. Load other domain skills or `load_domain_skill("lateral_thinking")` when the picture stops making sense.
- Nothing here forbids a lateral search. The only hard limits are the platform rules: read-only, evidence-only, configuration-first.
- Routing note: the device selector parameter on every tool is `device` (the component id from the tenant inventory).

## The FortiGate Logging Model (mental map)

A log entry exists at the intersection of three independent dimensions. A "no logs" verdict is only valid after checking all three.

**1. Storage backend** — up to four independent stores; configuration decides which are active:

1. **FortiAnalyzer** — remote, best retention. An HTTP 424 or connection error means the backend is misconfigured or unreachable, **not** that logs do not exist elsewhere.
2. **FortiCloud** — remote, requires an active subscription and enabled connection.
3. **Disk** — local, only on models with SSD/disk. On diskless models (e.g. FGT-60E/-F desktop units) disk logging is disabled by hardware design — a finding of scope, not a fault.
4. **Memory** — local, always present, volatile: a short recent window that is lost on reboot.

When the device reports FortiAnalyzer or FortiCloud connected, they are the preferred sources (retention). Local stores are first-class fallbacks when remote backends fail — check them before concluding logs are unavailable, but do not skip healthy remote backends in their favor.

**2. Log category** (the `type` path parameter): `traffic`, `event`, `webfilter`, `virus`, `ips`, `dns`, `app-ctrl`, `anomaly`, `ssl`, `ssh`, `file-filter`, `emailfilter`, `dlp`, `voip`, `waf`. Subtypes: `traffic` → forward/local/multicast/sniffer; `event` → system/vpn/user/router/wireless/ha/endpoint/security-rating.

- "What websites did a host visit" → `webfilter` logs (URL, hostname, category, action).
- "What did a host connect to" → `traffic` subtype `forward` (dstip, port, service, bytes; hostname only when inspection applied).

**3. Generation** — a log only exists if the feature that produces it was applied to the policy that carried the traffic. No webfilter profile on the policy → no webfilter logs, ever, in any backend. That is a configuration finding that answers the ticket, not a dead end.

## Verified Evidence Anchors (read-only)

| Tool | What it answers |
|---|---|
| `fgt_cmdb_log_get_device_state` | **Always first.** Which log storage backends are enabled/available on this device (disk, memory, FortiAnalyzer, FortiCloud). Decides the rest of the investigation. |
| `fgt_cmdb_faz_get_fortianalyzer_type` | Historical log entries from FortiAnalyzer by category (`type=webfilter`, `traffic`, `event`, ...). Variants: `fgt_cmdb_faz_get_fortianalyzer_traffic_subtype`, `..._event_subtype`, and `..._raw` forms. |
| `fgt_cmdb_fcloud_get_forticloud_type` | Historical log entries from FortiCloud by category. Same subtype/`_raw` variants (`fgt_cmdb_fcloud_get_forticloud_traffic_subtype`, ...). |
| `fgt_cmdb_disk_get_type` | Historical log entries from the local disk by category — only when device_state shows disk logging available. Variants: `fgt_cmdb_disk_get_traffic_subtype`, `fgt_cmdb_disk_get_event_subtype`, and `..._raw` forms. |
| `fgt_log_mem_get_memory_type` | Log entries from local memory — the always-present fallback, short volatile window. Variants: `fgt_log_mem_get_memory_traffic_subtype`, `..._event_subtype`, `..._raw` forms. |
| `fgt_cmdb_log_get_fortianalyzer` / `fgt_cmdb_log_get_fortianalyzer_queue` | FortiAnalyzer logging state and transmit queue — diagnoses a 424/unreachable backend. |
| `fgt_cmdb_log_get_forticloud` / `fgt_cmdb_log_get_forticloud_connection` | FortiCloud logging state and connection status — diagnoses a disabled/failing cloud backend. |
| `fgt_cmdb_log_get_stats` / `fgt_cmdb_log_get_current_disk_usage` | Log volume per category/device and disk usage — corroborates whether a category generates data at all. |
| `fgt_cmdb_log_get_historic_daily_remote_logs` | Daily volume of logs sent to remote backends — evidence of what the remote source should hold. |
| `fgt_cmdb_log_get_local_report_list` / `fgt_cmdb_log_get_forticloud_report_list` | Pre-generated local/FortiCloud reports (and `..._download` counterparts). |
| `fgt_cmdb_search_post_abort_session_id` | Ends a paginated log search session. A POST, but it only terminates your own search session — non-mutating. |

Retrieval parameters (shared by all four backend families): `type` or `subtype` (path, required), `rows` (int), `session_id` (int — pagination: repeat the call with the same id to continue; there is no start/offset), `serial_no`, `is_ha_member`, `filter` (array of expressions, e.g. `srcip==192.168.1.10`; operators `== != =@ !@ <= < >= >`), `extra` (`reverse_lookup|country_id`; not available on `_raw` variants).

Catalog queries that rank these tools (calibrated against this index):

- `"historical web browsing logs visited websites by source IP"` → retrieval tools
- `"log storage backends enabled disk memory fortianalyzer"` → device state
- `"traffic logs stored locally on the device"` → disk/memory retrieval
- `"webfilter log entries URL category"` → webfilter retrieval

## Investigation Sequence (starting frame)

1. **`fgt_cmdb_log_get_device_state` first — never skip it.** It tells you which backends can hold data before you spend calls on ones that cannot.
2. **Pick the backend by evidence**: remote (FortiAnalyzer, then FortiCloud) when device_state shows it connected/enabled; on remote failure or disabled state, fall back to disk (if available) and then memory. Diagnose a failing remote backend with its state anchors (`fgt_cmdb_log_get_fortianalyzer`, `fgt_cmdb_log_get_forticloud_connection`) — report the cause, then continue on a local store.
3. **Pick the category from the question**: browsing → `type=webfilter`; connections → `traffic` + subtype `forward`. Scope with `filter` (e.g. `srcip==<host>`) and a moderate `rows`.
4. **Empty result → classify it before concluding** (see Interpreting below). Check `fgt_cmdb_log_get_stats` to see whether that category generates volume at all.
5. **Lateral fallback**: if webfilter logs do not exist, traffic forward logs for the same `srcip` still give destinations, ports, and volumes — partial but real evidence of navigation.
6. If you paginated with `session_id`, close the session with `fgt_cmdb_search_post_abort_session_id`.

Skip steps the evidence has already answered. Add steps this frame does not list if the evidence demands it.

## Interpreting Log Retrieval Responses

- Responses carry the entry array plus session metadata (`session_id`, progress/total). If the result is incomplete, repeat the same call with the returned `session_id` until complete.
- Webfilter fields: `srcip`, `user`, `hostname`, `url`, `catdesc` (category), `action` (passthrough/blocked), `date`/`time`.
- Traffic fields: `srcip`, `dstip`, `dstport`, `service`, `policyid`, `sentbyte`/`rcvdbyte`, `action`; `hostname` appears only with inspection applied.
- `extra=reverse_lookup` enriches IPs with names (not on `_raw` variants).
- **Empty ≠ error.** Distinguish four causes and say which one applies:
  1. the backend store is disabled/unavailable (device_state evidence),
  2. the feature never generated the log (no profile on the policy — configuration finding),
  3. the retention window was exceeded (memory is short and lost on reboot — state the observed window),
  4. the filter expression is malformed (retry unfiltered with small `rows` to discriminate).

## Safety Rail — tools you must NOT execute

The catalog also indexes mutating log tools:

- `fgt_cmdb_log_post_stats_reset` — **indexed and executable**: resets logging statistics on all log devices. Never execute it.
- Blocked from the index but do not propose them blindly in plans either: `fgt_cmdb_log_post_local_report_delete`, `fgt_monitor_sys_post_logdisk_format` (destroys all disk logs), `fgt_cmdb_log_disk_filter_delete_custom_field_id`.

If resolution requires enabling or repairing a logging backend (FortiAnalyzer registration, FortiCloud activation, logging settings), put the action in the recommended plan with its impact and set `case_status` to `needs_human`. Never execute configuration changes.

## Common Pitfalls

- **A failing remote backend ≠ "no logs".** FortiAnalyzer 424 / FortiCloud disabled are backend states; disk and memory are independent stores that may still answer the ticket. This is the single most common dead end.
- **Diskless models**: on hardware without SSD, disk logging disabled is by design — memory is the local store. Do not report it as a fault.
- **Memory is volatile and short**: absence in memory does not prove the activity never happened. Report the time window actually covered by the entries you retrieved.
- **Webfilter logs require a webfilter profile** on the policy that carried the traffic. Their absence with traffic logs present is a visibility-configuration finding that directly answers "what did the host browse": the environment does not record it.
- **`fgt_cmdb_log_disk_filter_*` tools (115 of them) are logging CONFIGURATION** (`/api/v2/cmdb/log.*`) — useful to verify what is being logged and where (including syslog destinations), useless for reading entries.
- **Misleading names**: disk retrieval is `fgt_cmdb_disk_get_*`, memory retrieval is `fgt_log_mem_get_memory_*` — do not infer capability from names.
- **Pagination**: without `session_id` every call restarts the search; use `rows` + the returned `session_id` to walk large datasets.

## Reporting

Present the log source verdict as a Markdown table, then follow the base Output Contract for the ticket mode:

| Backend | State (evidence) | Category queried | Filter | Entries | Time window covered |
|---|---|---|---|---|---|

State explicitly which backends were verified, which were ruled out and why (device_state, connection errors), and — when the answer is negative — which of the four empty-result causes applies.
