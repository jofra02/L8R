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
- `subitems` — discovered sub-inventory rules: a list step yields many
  sub-entities of the parent asset (e.g. one FortiEDR console → many
  `endpoint` collectors), upserted into **`asset_subitems`** — never into
  `assets`. Assets are curated (human/import created, ref-unique,
  type-validated, lifecycle-managed); discovery only provides visibility,
  and the separate table makes that invariant structural rather than a
  filter every consumer must remember. Rule shape: `step`, `items`,
  `kind`, `identity` = `(source, external_id path, fallback)`, `name`
  path, optional `state` path + `state_map`, and `attributes` mappings
  (targets restricted to `attributes.<key>`, no merge policy — subitems
  are wholly source-owned). Items without identity are skipped with a
  warning. After a **complete** scan (not truncated by the pagination
  cap — `meta.truncated` guards this), rows the source no longer returns
  are flagged `absent=true` (cleared when they reappear); **rows are
  never deleted** — retirement visibility is the point of the flag.
  Promotion of a subitem to a curated asset is a future explicit action
  (`promoted_asset_id` reserves the link).

  Replaced the pre-v3 `produces` rules (which materialized discoveries as
  child assets); old snapshots containing `produces` still parse (ignored
  by the schema) and simply create nothing.

Shipped packs: `fortigate@3` (fgt74: status, license, firmware,
performance, interfaces, HA, VDOMs, LLDP; v2 was a no-op bump — the schema
dropped `produces` and `content_hash` covers the canonical dump, so the
v1 file no longer hash-matched its snapshot; v3 normalizes the license
step through `fortigate.license_status` → `attributes.licenses`) and
`fortiedr@5` (fedr62: system summary + org-scoped `organizations` +
dashboard license pair + paginated collectors → endpoint subitems; v4
added the license normalization, v5 added the
`/api/dashboard/license-*-per-organization` steps after live verification
showed hosted org-scoped credentials 403 on BOTH admin/* and
list-organizations — the dashboard family auto-scopes from the basic-auth
org and is their only reachable license source. Mapping precedence:
dashboard baseline → summary → organizations). See "License inventory"
in `docs/assets.md` for the normalized model.

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

Subitems carry no provenance and no audit rows by design: they are 100%
discovered, and the per-item change trail is covered by
`first_seen_at`/`last_seen_at`/`last_sync_run_id` plus run stats. Their
attributes also bypass the sensitive-field redaction (no type schema);
exposure is the same `assets:read` permission that covered them before.

Every run audits the parent's work in `asset_audit_log` with actor
`system:enrichment` and the `sync_run_id` (action `enriched`), and
records `stats`
(`steps_total/steps_failed/assets_updated/subitems_created/
subitems_updated/subitems_absent/relations_created/warnings`) on the run
row for the UI (historical runs may carry the pre-v3 `assets_created`
key instead).

## Adding a new integration

1. Author `definitions/packs/<vendor>.yaml` with literal tool names from
   `mcp_gateway/baseline_tools.txt` (read-only GETs only — validated at
   load) and, if needed, a new normalizer in
   `src/assessments/normalizers.py`.
2. Declare `compatible.device_types` matching the gateway pack's
   `device_type`, and target asset types (add a type YAML if needed).
3. Startup sync snapshots the pack; a version bump is required for any
   later change.
