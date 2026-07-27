# Skill: FortiEDR Event Triage — Malicious or Benign Verdict

## Purpose

Adjudicate a FortiEDR security event: build an evidence-backed verdict (malicious / benign false positive / PUP / inconclusive→human) by converging four independent evidence axes — this skill is the reasoning method, not a platform manual.

## How to Use This Skill

- Load for tickets that implies analize FortiEDR security events.
- **Load `fortiedr.md` alongside this skill** — it carries the platform mechanics this skill assumes: time formats (`yyyy-MM-dd HH:mm:ss` for events/hunting), the silent-zero `device` filter trap, org scoping, empty-result classification.
- **Anchor names are pre-verified: pass them directly to `execute_tool`.** Search is discovery, not permission.
- FortiEDR's own `classification` (`Malicious`, `Suspicious`, `Inconclusive`, `PUP`, `Likely Safe`, `Safe`) is an **input to triage, not the verdict**. Your job is to corroborate or refute it with independent evidence.
- Hard limits as always: read-only, evidence-only.

## The Verdict Model — convergence of four evidence axes

No single field decides. Weigh all four; a verdict is strong when they agree and inconclusive when they diverge:

1. **Artifact identity** — what the process/file IS: path, signature (`signed`), hash, associated product/vendor.
2. **Prevalence & history** — where else and since when it appears across the estate.
3. **Behavior** — what it DID around the event: child processes, file writes, network connections, registry activity.
4. **Organizational context** — existing exceptions, policy mode, collector state, logged user.

## Verified Evidence Anchors (read-only)

| Tool | Triage role |
|---|---|
| `fedr62_mgmt_events_get_list` / `fedr62_mgmt_events_get_count` | Acquire the event: classification, action, rule, process path, hash, `signed`, `loggedUser`, `destinations`, first/last seen, collector. |
| `fedr62_mgmt_events_get_list_raw_data_items` | Per-event forensic rows (`eventId`) — the underlying detection detail behind the aggregated event. |
| `fedr62_mgmt_incidents_get_incident_id_processes` | Process tree of the incident — the parent→child chain around the flagged process. |
| `fedr62_mgmt_hash_search_get` | **Central IOC pivot** (`fileHashes` required, array): cross-references a hash against current events, the threat-hunting repository, and communicating applications in one call. |
| `fedr62_mgmt_threat_hunting_search` / `_counts` / `_facets` | Behavior around the event: Lucene-like `query` over Process/File/Network/Registry telemetry, scoped to the device and a window bracketing the event. |
| `fedr62_mgmt_exceptions_get_event` / `fedr62_mgmt_exceptions_get_list` | Has the organization already adjudicated this pattern? |
| `fedr62_mgmt_communication_control_get_comm_list_products` | Vendor/reputation context for the communicating application. |
| `fedr62_mgmt_playbooks_policies_get_list` | What action policy maps to each classification — reveals simulation mode. |
| `fedr62_mgmt_system_inventory_get_list_collectors` | Collector state (bounds telemetry completeness) + the only valid source of `device` names. |

## Triage Sequence

1. **Acquire the event**: `fedr62_mgmt_events_get_list` by `eventIds` (or the ticket's process/device/window filters). Record: classification, `action`, rule, process path, hash, `signed`, `loggedUser`, `destinations`, firstSeen/lastSeen, collector. `action=Log` or `SimulationBlock` means the code **executed** — raises urgency if the verdict lands malicious.
2. **Detail it**: `fedr62_mgmt_events_get_list_raw_data_items` for the `eventId`; if an incident exists, pull the process tree (`fedr62_mgmt_incidents_get_incident_id_processes`). An anomalous parent (Office spawning a script host, a service launching a shell) weighs more than the flagged process itself.
3. **Identity axis**: `fedr62_mgmt_hash_search_get` with the file hash. Signed + known product + wide presence → benign lean. Unsigned + user-writable path (%TEMP%, %APPDATA%, Downloads) + hash unknown → malicious lean. A hash absent from the estate proves rarity, NOT malice.
4. **Prevalence axis**: `fedr62_mgmt_events_get_count` pivoting on `process`/`fileHash` with NO device filter and a wide window. One host + recent = targeted/suspicious lean; many hosts + months of history = likely FP/PUP lean (correlation, not proof — propagation also looks widespread).
5. **Behavior axis**: `fedr62_mgmt_threat_hunting_search` on the same device, window bracketing the event: children of the process, writes to persistence locations (Run keys, Startup, scheduled tasks, services), outbound connections to raw IPs or rare destinations, credential access. A benign-looking artifact with attack-chain behavior is malicious — the chain outweighs the binary.
6. **Context axis**: `fedr62_mgmt_exceptions_get_event` (already excepted/adjudicated?); `fedr62_mgmt_playbooks_policies_get_list` (policy in simulation mode is a finding in itself); collector state via `fedr62_mgmt_system_inventory_get_list_collectors` whenever telemetry looks incomplete.
7. **Verdict**: converge the four axes. Attribution/exoneration rules from the base skill apply — no claim without cited tool output. Axes diverging, or telemetry gaps you cannot close → verdict `Inconclusive`, `case_status=needs_human`. Never manufacture certainty.
8. **Blast radius (only on malicious/likely-malicious)**: re-run `fedr62_mgmt_hash_search_get` and `fedr62_mgmt_threat_hunting_search` estate-wide with the confirmed IOCs (hash, destinations, paths) to size the spread. Containment goes in the recommended plan — never executed.

## Indicator Rubric

Malicious-lean:
- Unsigned binary executing from a user-writable path.
- Filename imitating a system binary outside its canonical path (`svchost.exe` outside System32).
- Office apps/browsers spawning script interpreters (powershell, wscript, mshta, rundll32).
- Persistence writes (Run keys, Startup, scheduled tasks, service creation) near the event.
- C2-like network behavior: raw-IP destinations, non-standard ports, periodic beaconing.
- Hash with no product correlation anywhere in the estate.

Benign-lean:
- Signed by a known vendor with an install path coherent with that product.
- Wide, long-standing presence across the estate predating the ticket.
- Existing exception or prior adjudication for the same pattern.
- Behavior consistent with the product's function (an updater writing to its own directory, a backup agent reading many files).
- Triggering rule known for false positives with that software.

## Pitfalls (triage-specific; platform traps live in `fortiedr.md`)

- **Do not echo FortiEDR's `classification` as your verdict** — an `Inconclusive` you corroborated is worth more than a `Malicious` you merely repeated.
- **`SimulationBlock` = it ran.** Never report it as "blocked".
- **An empty hunting result ≠ no activity** — retention limits and degraded/disconnected collectors also produce silence. Verify collector state before exonerating on absence.
- **Hash absent from `hash_search` ≠ malicious; hash present on many machines ≠ benign** (propagation is also widespread).
- **Do not use `fedr62_mgmt_forensics_get_event_file` / `fedr62_mgmt_forensics_get_file`** — they return binary ZIP streams unusable in this loop; the raw data items and hunting telemetry are the workable evidence.

## Safety Rail — tools you must NOT execute

Triage produces a verdict, never a response action. The following are blocked or out of bounds — never execute or work around: `fedr62_mgmt_events_create_exception`, `fedr62_mgmt_events_update`, `fedr62_mgmt_events_delete`, `fedr62_mgmt_forensics_remediate_device`, collector isolation/unisolation/move/toggle/uninstall, exception/exclusion writes, incident handling updates, saved-query writes. If the verdict warrants response (isolate the host, create an exception, take a policy out of simulation), put it in the recommended plan with impact and set `case_status=needs_human`.

## Reporting

Lead with the verdict and confidence (e.g. "Malicious, high confidence — three of four axes converge; behavior axis decisive"), then the evidence table:

| Axis | Tool | Finding | Weight |
|---|---|---|---|

Follow with: identified IOCs (hashes, paths, destinations), blast radius if assessed, and recommended actions as a plan. When the verdict is `Inconclusive`, state exactly which axis is missing evidence and what a human analyst should collect next.
