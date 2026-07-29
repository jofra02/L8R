# Asset Enrichment — deterministic MCP collection

Deterministic discovery/enrichment of managed assets through the MCP
gateway. Everything is pinned by versioned pack definitions; **the LLM
plays no part**: tools, parameters, mappings and conflict resolution are
all declarative YAML executed by `src/assets/enrichment/engine.py`.

## Enrichment packs

`src/assets/definitions/packs/*.yaml`, snapshotted immutably into
`asset_definition_versions` (`kind=enrichment_pack`). Runs pin the exact
`(pack_id, version)` snapshot they were queued with.

A pack declares:

- `compatible.device_types` — resolved against the asset's
  `mcp_config.device_type` (e.g. `fortios`, `fortiedr`);
  `compatible.asset_types` produces a warning on mismatch.
- `steps` — collection steps (same shape as assessment
  `CollectionStepDef`): literal gateway tool name (validated against the
  read-only allowlist at load), `params`, `required`, `depends_on`,
  `normalizer` (resolved at load; `passthrough` and `fortiedr.results`
  handle envelope-less APIs), `timeout_s`, `max_attempts`, `sanitize`
  (field redaction before use), plus the pack-specific `paginate`
  (`page_param`/`size_param`/`size`/`max_pages`/`start_page`) for large
  list endpoints such as FortiEDR collectors.
- `mappings` — self-enrichment: dotted-path `source` into the normalized
  step output → `target` (mappable common column or `attributes.<key>`),
  optional `transform` (`to_datetime|to_date|lowercase|first|join`) or
  `value_map`, and a merge `policy`.
- `relations` — match-only rules: link the asset to EXISTING assets by
  matching a discovered value (e.g. LLDP `chassis_id`) against an asset
  field (`attributes.mac`). Never creates assets.
- `produces` — child-asset rules: a list step yields many child assets
  (e.g. one FortiEDR console → many `endpoint` collectors), upserted by
  `identity` = `(customer_id, external_source, external_id)` with an
  optional fallback path (MAC), plus a child→parent `relation`
  (`managed_by`). Items without identity are skipped with a warning.
  **Absent children are never deleted** and soft-deleted children are
  never resurrected — retirement is a human decision.

Shipped packs: `fortigate@1` (fgt74: status, license, firmware,
performance, interfaces, HA, VDOMs, LLDP) and `fortiedr@1` (fedr62:
system summary + paginated collectors → endpoint children).

## Execution model

- Triggers: **auto** (queued after a successful gateway sync when an asset
  is marked managed), **manual** (`POST /assets/{id}/enrich`, UI button),
  **scheduled** (`ASSETS_SYNC_INTERVAL_HOURS`, default 24h, `0` disables;
  in-process loop, tick every 15 min).
- State machine: `pending → running → completed |
  completed_with_errors | failed` (validated transitions, own session per
  transition — assessments pattern). One active run per asset (409).
  Startup sweeper fails runs orphaned by a restart.
- Collection: steps run sequentially in dependency order via
  `execute_mcp_tool(enforce_read_only=True)` — the framework injects
  `tenant`; the engine injects `device` = the asset `ref`. Retries only
  `{connection, timeout}` with exponential backoff. A required-step
  failure fails the run; optional failures yield
  `completed_with_errors` with per-step errors in `stats`.
- Concurrency: global semaphore `ASSETS_SYNC_CONCURRENCY` (default 4).

## Provenance & conflict policy

Every asset field carries provenance
(`assets.provenance[target] = {source: manual|discovered, pack_id,
run_id, updated_at}`):

- Manual writes (API/UI/import) stamp `source: manual`.
- `manual_wins` (default): discovery never overwrites a non-empty value
  whose provenance is `manual` — or unknown (pre-existing/backfilled data
  is treated as manual). Empty fields are filled; previously-discovered
  values keep updating.
- `discovered_wins`: discovery always overwrites (used for device-owned
  facts like serial numbers).
- The UI shows the manual/discovered origin per attribute; provenance is
  never exposed through the legacy ClientContext adapter.

Every run audits its work in `asset_audit_log` with actor
`system:enrichment` and the `sync_run_id` (parent `enriched`, children
`created`/`enriched`), and records `stats`
(`steps_total/steps_failed/assets_created/assets_updated/
relations_created/warnings`) on the run row for the UI.

## Adding a new integration

1. Author `definitions/packs/<vendor>.yaml` with literal tool names from
   `mcp_gateway/baseline_tools.txt` (read-only GETs only — validated at
   load) and, if needed, a new normalizer in
   `src/assessments/normalizers.py`.
2. Declare `compatible.device_types` matching the gateway pack's
   `device_type`, and target asset types (add a type YAML if needed).
3. Startup sync snapshots the pack; a version bump is required for any
   later change.
