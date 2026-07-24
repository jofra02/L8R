# Skill: FortiEDR Endpoint Security Investigation

## Purpose

Investigate endpoint security events, incidents, collector health, and endpoint telemetry on FortiEDR management consoles (`fedr62_*` tools) — and pick the right data family for the question, because each family has its own time idiom and traps.

## How to Use This Skill

- **Anchor names are pre-verified: pass them directly to `execute_tool`.** Search is discovery, not permission.
- Load this skill for any ticket about endpoint detections, malware/ransomware activity, security events, EDR agents (collectors), or endpoint telemetry.
- **NEVER pass `device` to `fedr62_*` tools out of routing habit.** Console routing is automatic. Where these tools accept `device`, it is a FILTER by FortiEDR entity name (collector hostname; core/aggregator on log tools) — passing the platform component id (e.g. `fortiedr-01`) matches no entity and returns HTTP 200 with zero results, silently. Only pass it with a hostname taken verbatim from `fedr62_mgmt_system_inventory_get_list_collectors` output.
- **Pass only the filters the question needs.** Boolean params (`signed`, `seen`, `muted`, `archived`, `handled`, `expired`, ...) are filters, not defaults — setting `signed=false` restricts to unsigned processes, `seen=false` to unseen events. Every unnecessary filter silently narrows the answer.
- Hard limits as always: read-only, evidence-only.

## The FortiEDR Data Model (mental map)

Pick the family by what the question actually asks:

1. **Security events** (`events` family) — the primary detection record: one event per process/rule detection with classification, action, and the affected collector device. "Were there security events?" answers HERE.
2. **Incidents** (`incidents` family) — the aggregated triage view built on top of events (`incidentAggregationType: SecurityEvents`). Good for handling state and analyst workflow, not the ground-truth detection list.
3. **Raw data items** — per-event forensic telemetry, keyed by `eventId`.
4. **Threat hunting** — searches ALL collected endpoint telemetry (process, file, network, registry activity), independent of whether anything was detected.
5. **System events** — the console's own audit trail (services, config changes). NOT endpoint security events.
6. **Dashboard** — pre-aggregated summaries (detection activity, unhandled counts, top affected devices).

## Two Time Idioms — never mix them (live-verified)

- **Events + threat-hunting custom ranges**: date strings `yyyy-MM-dd HH:mm:ss` (space separator). ISO 8601 with `T`/`Z` and epoch values are rejected with HTTP 400. Params: `firstSeenFrom`/`firstSeenTo`/`lastSeenFrom`/`lastSeenTo`.
- **Incidents family**: `timeFilter` enum (`Last1days`…`Last90days`, `All`, `Custom`); `startDate`/`endDate` are epoch **milliseconds** and only honored with `timeFilter=Custom` — epoch seconds are read as 1970 and return an empty result silently.

Organization scoping (both families): **omit** `organization`/`organizationId` — an org-scoped API credential is scoped automatically and wrong values return HTTP 400. Where an id is strictly required, use the `accountId` from incident responses; where a name is accepted, only the exact organization name works — never the platform tenant id.

## Verified Evidence Anchors (read-only)

| Tool | What it answers |
|---|---|
| `fedr62_get_inventory_tree` | Routable consoles for this tenant. |
| `fedr62_mgmt_events_get_count` | **Bound first.** Event count for a filter set — cheap, run it before listing and re-run it unfiltered to interpret empty results. |
| `fedr62_mgmt_events_get_list` | **The security events list.** Filters: `eventType=SecurityEvent`, `classifications`, `actions`, `handled`, seen-window params, `device` (collector name), `process`. Paging: `itemsPerPage` (default 100, max 1000) + `pageNumber`. |
| `fedr62_mgmt_events_get_list_raw_data_items` | Forensic telemetry for one event (`eventId`). |
| `fedr62_mgmt_incidents_get` | Aggregated incidents (`typeFilter=SecurityEvents`, `statusFilter`, `timeFilter`). |
| `fedr62_mgmt_incidents_get_incident_id_events` | The events behind one incident. |
| `fedr62_mgmt_system_inventory_get_list_collectors` | Collector (agent) health per endpoint — degraded/disconnected collectors bound what the console can even see. |
| `fedr62_mgmt_dashboard_get_*` | Estate-wide summaries (detection activity, unhandled items, top affected devices) — one call replaces manual aggregation. |
| `fedr62_mgmt_threat_hunting_search` / `fedr62_mgmt_threat_hunting_counts` / `fedr62_mgmt_threat_hunting_facets` | Telemetry hunting (read-only POSTs, exempted by design). Own `time` enum (`lastHour`…`custom`) + `yyyy-MM-dd HH:mm:ss` custom range. |
| `fedr62_mgmt_system_events_get_list` | Console/system audit trail — console-health questions only. |

## Investigation Sequence (starting frame)

1. **Count before you list**: `fedr62_mgmt_events_get_count` with the ticket's window (`firstSeenFrom=yyyy-MM-dd HH:mm:ss`) and filters. It bounds the work and is the cheapest probe of data visibility.
2. **List**: `fedr62_mgmt_events_get_list` with the same filters plus `eventType=SecurityEvent`; add `handled=false` when the ticket is about open items. Page only if the count demands it.
3. **Empty result → classify before concluding**: re-run the count with ONLY `eventType=SecurityEvent` — no date filter, no `device`, no boolean filters. Total > 0 with window = 0 means genuinely no events in the period (a valid answer). Total > 0 with your filtered query = 0 means a filter (usually `device` or a boolean) excluded everything — fix the query. Total = 0 means a visibility problem (credential scope, collectors down) — check `fedr62_mgmt_system_inventory_get_list_collectors` before reporting absence.
4. **Detail what matters**: raw data items per `eventId`; incident context via the incidents family when handling state matters.
5. **Summarize wide questions** with the dashboard family instead of aggregating lists yourself.
6. **Hunt** with the threat-hunting anchors only when the question concerns activity NOT surfaced as detections.

## Interpreting Events

- `classification` scale: `Malicious`, `Suspicious`, `Inconclusive`, `PUP`, `Likely Safe`, `Safe`. Report the distribution, not just the count.
- `action`: `Block` (prevented), `Log` (recorded only), `SimulationBlock` — the policy is in simulation mode: it WOULD have blocked but did not. Simulation mode on a malicious event is a finding in itself.
- `handled`/`incidentHandlingState` distinguish analyst workflow from detection facts.
- The `severities` filter is marked Deprecated — filter and report by `classifications`.

## Pitfalls (each one cost a real investigation)

- **`device=<platform component id>` zeroes every events query silently** (200, no error). If any events/count call returned 0, first re-run it WITHOUT `device` and without unnecessary boolean filters before drawing any conclusion.
- **Mobile-family tools are not a fallback.** `fedr62_mgmt_mobile_*` and mobile inventory serve the mobile (iOS/Android) protection module only; consoles without it return HTTP 404 for every path. A 404 there says nothing about the integration or the main endpoints.
- **`fedr62_mgmt_incidents_get_search_info` returns HTTP 400 for org-scoped credentials** — do not use it to discover filter values; the enums are already in each tool's schema.
- **Do not carry a date format across families** (epoch ms belongs to incidents-Custom only; `yyyy-MM-dd HH:mm:ss` belongs to events/hunting).
- **Absence of events is only evidence after step 3's classification** — "no results" with an unverified filter set proves nothing.

## Safety Rail — tools you must NOT execute

FortiEDR exposes response actions; this platform is read-only. Never execute or propose executing: collector isolation/unisolation, move/toggle/uninstall collectors, event or incident handling updates, exception creation, tag writes, report generation side effects. If remediation is warranted (isolate a host, handle an event, fix a policy in simulation mode), put it in the recommended plan with its impact and set `case_status` to `needs_human`.

## Reporting

Lead with the verdict for the ticket's window, then the evidence table:

| First seen | Device | Process | Classification | Action | Handled |
|---|---|---|---|---|---|

State the exact filter set and time window behind every count, and — when reporting absence — which step-3 branch proved it.
