# Asset Inventory Module

MSP multi-tenant asset inventory: relational storage, schema-governed
extensible attributes, server-side search/filter/sort/pagination, RBAC,
per-asset audit, soft delete, CSV/XLSX export, non-destructive import,
cross-tenant MSP search, and deterministic MCP-gateway enrichment
(see [assets_enrichment.md](assets_enrichment.md)). **No LLM participates
anywhere in this module.**

## 1. Diagnosis of the previous module

The pre-migration "inventory" was not relational: every component,
dependency, baseline and known change lived in a single JSON blob per
tenant (`client_contexts.content`), versioned by full-document
copy-on-write. Consequences:

- No per-asset primary key, indexes, or FK targets
  (`AssessmentTargetORM.component_id` was a plain string for this reason).
- No server-side pagination, filtering, sorting or search.
- No per-asset audit trail, no soft delete; import was a destructive
  full replace; known changes were keyed by list index (racy).
- Every component edit rewrote the whole context row (row growth).

What was already right and is preserved verbatim:

- The MCP gateway sync contract: local write first with
  `sync.status="pending"` (committed), then the gateway call, then a second
  commit with the outcome — the gateway never holds a device the app has no
  record of.
- The token is write-only: forwarded to the gateway (Fernet-encrypted at
  rest there), never persisted or returned app-side.
- `GatewayAdminClient` resilience: never raises into the request path,
  self-heals `unknown_tenant`, PATCH↔POST fallback, delete-404 = synced.

## 2. Decision: refactor to relational + compatibility adapter

Full replacement was rejected (it would break the Engineer agent,
assessments and topology seeding); a parallel module was rejected (two
sources of truth, duplicated MCP sync). Instead:

- New tables `assets`, `asset_relations`, `asset_definition_versions`,
  `asset_sync_runs`, `asset_audit_log`, `asset_subitems` are the
  **source of truth** for components and dependencies.
- A read adapter (`src/assets/context_adapter.py`) reassembles the exact
  pre-migration `ClientContext` Pydantic shape, so the five consumers
  (`assessment_service.create_run`, `engineer_tools.query_client_db`,
  `pack_matching`, `topology_utils.seed_topology_from_context`,
  seed scripts) keep working unchanged — including the reconstructed
  `metadata["mcp"]` block.
- `baselines` / `known_changes` stay in the blob (assessment-adjacent;
  inherited debt, documented below).
- The legacy `/inventory` component/dependency endpoints are delegating
  shims over `AssetService` with identical response shapes, kept for one
  release and then retired.

## 3. Architecture

```
src/assets/
  schema.py            # Pydantic models for asset-type + enrichment-pack YAML
  registry.py          # YAML -> immutable DB snapshots (content_hash, immutability)
  validation.py        # deterministic attribute validation vs type schemas
  service.py           # AssetService: CRUD, audit, gateway sync, search builder
  context_adapter.py   # assets tables -> ClientContext compatibility shape
  io.py                # CSV/XLSX export, CSV/JSON non-destructive import
  definitions/
    types/*.yaml       # asset-type schemas (versioned, immutable)
    packs/*.yaml       # enrichment packs (versioned, immutable)
  enrichment/
    engine.py          # deterministic run engine + state machine + sweeper
    scheduler.py       # periodic re-enrichment loop (in-process)
    mappings.py        # pure path extraction / transforms / merge policy
src/api/routers/assets.py   # 20 endpoints (see below)
src/api/schemas/assets.py
```

### Sub-inventory (`asset_subitems`)

The domain distinguishes two entity classes with different invariants:

- **Assets** are *curated* inventory: created by a human or an explicit
  import, ref-unique per tenant, validated against a type schema, and
  lifecycle-managed (warranty, EOL, criticality, ownership).
- **Subitems** are *discovered* observations owned by an external source
  (e.g. the FortiEDR console's collector list): high-churn, not curated,
  attached to the parent asset they were discovered through.

Modeling both in `assets` would make the semantics of "asset"
conditional (`asset WHERE NOT discovered`) and turn a structural
invariant into a per-consumer filtering obligation — a missed clause
produces silent semantic corruption (wrong counts, exports, agent
context), not a loud error. The separate table makes the invariant
"`assets` contains only curated inventory" hold by construction: counts,
exports, import matching, ClientContext and gateway sync are correct
without qualifiers.

Consequences:

- Enrichment `subitems` rules upsert into `asset_subitems` by
  `(customer_id, parent, source, kind, external_id)`; rows missing from
  a complete scan are flagged `absent`, never deleted.
- The parent asset exposes an aggregate (`subitems_summary`:
  `{kind: {total, by_state, absent}}`) on list and detail responses and
  as `metadata["subitems"]` in the ClientContext component — the agent
  sees counts, not thousands of rows.
- Promoting a subitem to a real asset is a future explicit curation
  action (`promoted_asset_id` reserves the link); the promote flow must
  copy the external identity so import matching stays coherent.

Persistence notes:

- **Deliberate deviation:** asset tables use PostgreSQL `JSONB` + GIN
  indexes (containment filters over dynamic attributes and tags) instead of
  the repo-wide `sa.JSON` convention. The deployment is Postgres-only
  (asyncpg DSN, partial indexes, `pg_insert` already in use). The ORM
  carries a sqlite variant purely for the self-contained test suite.
- Soft delete via `deleted_at`; partial unique indexes
  `(customer_id, ref)` and `(customer_id, external_source, external_id)`
  apply to live rows only.
- Tenant isolation: `TenantMixin` FK + every query filters by
  `customer_id`; a cross-tenant id is a 404, never a 403.

### API surface (`/api/v1/assets`)

| Method | Path | Permission |
|---|---|---|
| GET | `/assets` | `assets:read` — pagination, `q` ILIKE (name/ref/serial/ip/fqdn/manufacturer/model), filters `asset_type,status,criticality,managed,sync_status,owner,tag` (repeatable), `attr.<key>=` (declared-filterable only, GIN containment), `sort` whitelist, `include_deleted` (manage) |
| GET | `/assets/global` | `assets:read_global` — cross-tenant; platform sentinel allowed without `?customer_id=`; extra `tenant` filter |
| GET | `/assets/export?format=csv\|xlsx` | `assets:read` — honors the same filters |
| POST | `/assets/import?dry_run&match_key=id\|ref\|serial_number\|external_id` | `assets:manage` — CSV or JSON, per-row results, non-destructive upsert |
| POST/GET/PATCH/DELETE | `/assets(/{id})` | write/read/write/write — DELETE is soft |
| POST | `/assets/{id}/restore` | `assets:manage` |
| GET | `/assets/{id}/history` | `assets:read` — per-asset audit log |
| GET/POST | `/assets/{id}/relations`, DELETE `/assets/relations/{rid}` | read/write/write |
| POST | `/assets/{id}/enrich` | `assets:manage` — 202 + run id |
| GET | `/assets/{id}/sync-runs`, `/assets/sync-runs/{rid}` | `assets:read` |
| GET | `/assets/{id}/subitems` | `assets:read` — discovered sub-inventory; filters `kind,state,q,absent`, paginated |
| GET | `/assets/types(/{type_id})` | `assets:read` — drives dynamic forms |
| GET | `/assets/mcp-packs` | `assets:manage` — passthrough to gateway `/admin/packs` |

Feature flag: `ASSETS_ENABLED` gates the router, the startup definition
sync, the stale-run sweeper and the scheduler (never the adapter).

### RBAC

`assets:read`, `assets:write`, `assets:manage` (restore, import, enrich,
sensitive fields), `assets:read_global` (MSP cross-tenant, v1 = platform
admin profiles only — delegated multi-tenant operators via
`AuthContext.available_tenants` are a documented follow-up). Seeded by
migration `a8b9c0d1e2f3` into the three system profiles.

### Audit

`asset_audit_log`: actor (`user:<id>` | `api_key:<id>` |
`system:enrichment`), action (`created|updated|deleted|restored|imported|
enriched|relation_added|relation_removed|sync_status_changed`), field-level
diff `{field: {old, new}}`, optional `sync_run_id`. Written in the same
transaction as the mutation.

## 4. Extensibility model (asset types)

Versioned YAML in `src/assets/definitions/types/` → immutable snapshots in
`asset_definition_versions` (same registry pattern as assessments:
sha256 `content_hash`; same version + different content is rejected at
startup sync — bump the version instead).

Each type declares fields with: `key` (snake_case, cannot shadow common
columns), `type` (`string|integer|number|boolean|date|datetime|enum|
string_list|ip|json`), `required` (must carry a `default`), `enum` values,
`validation` (pattern/min/max/max_length), and flags `filterable`
(exposed as `attr.<key>` query filter), `searchable`, `sensitive`
(requires `assets:manage` to view/edit — masked as `***` otherwise).

Versioning policy:

- Any change bumps `version`; snapshots are immutable.
- Writes validate against the latest version and stamp
  `assets.type_schema_version`; reads tolerate unknown/legacy attribute
  keys (never dropped).
- New required fields must declare a default.
- Destructive changes (remove/retype) = version bump + explicit data
  migration (admin action), never automatic.
- `generic` is the open escape hatch (`open_attributes: true`) for legacy
  roles without a dedicated type; legacy `Component.role` is always kept in
  `attributes.legacy_role` for exact round-trip through the adapter.

Starter set: `firewall`, `switch`, `router`, `access_point`, `server`,
`endpoint`, `edr_console`, `generic`.

## 5. MCP sync flow (summary)

Marking an asset managed (`mcp_connection` in create/update) follows the
pending-first contract, records `sync_status/sync_error/last_synced_at`
+ `mcp_config` (never the token), and — on success — queues an automatic
enrichment run. Full collection/mapping/provenance semantics:
[assets_enrichment.md](assets_enrichment.md).

## 6. Data migration

- `a8b9c0d1e2f3` — tables + permissions.
- `b9c0d1e2f3a4` — backfill from the active `client_contexts` blobs:
  role→type map (unknown → `generic` + `legacy_role`), priority→criticality
  (1→critical, 2→high, 3→medium, else low), `metadata["mcp"]` → managed
  columns, dependencies → `asset_relations` (dangling ids skipped with a
  warning). Defensive per-item handling; the blob is left untouched, so the
  rollback story is: downgrade drops the tables and the blob still holds
  the pre-migration inventory.
- `c0d1e2f3a4b5` — `asset_subitems` table + conversion of the discovered
  child assets the pre-v3 `produces` rules created
  (`created_by='system:enrichment'` + `external_source` set): parent
  resolved via their `managed_by` relation, converted rows hard-deleted
  (relations/audit cascade), unconvertible rows left untouched with a
  warning. Must deploy together with the new engine code — old code
  against a migrated DB would recreate endpoint assets on the next run.

## 7. Risks / known debt

- Baselines/known changes remain blob-owned (index-keyed known changes
  debt inherited; out of scope).
- Asset `id` is a global PK: the legacy shim can no longer create the same
  component id in two tenants (409). New API generates uuids; backfill
  remaps collisions to `<tenant>--<id>`.
- ILIKE search will not scale to very large tenants; structured filters use
  GIN. Future: generated tsvector column.
- `assets:read_global` v1 is platform-admin only (`available_tenants` is
  not yet populated by the auth middleware).
- The scheduler is an in-process asyncio loop (first in the repo): it dies
  with the process; the startup sweeper + next tick reconcile.
- The legacy `/inventory` import shim is now a non-destructive component
  upsert (assets absent from the payload are no longer deleted) while
  baselines/known changes keep replace semantics.
- The safety-filter fix (token matching) also hardened the catalog: ~495
  previously-allowed mutating `*_put_*` tools (plus the `vmlicense` POSTs)
  are now blocked, and 3 read-only GETs were unblocked — a Qdrant
  `tool_catalog` re-index is required to reflect the new universe
  (2776 → 551 name-blocked). See `src/testing/test_safety_regression.py`.
- `docs/integrations/api_reference.md` predates this module and needs a
  regeneration pass to include the `/assets` endpoints.

## 8. Files touched & validation

Backend (new): `src/assets/**`, `src/api/routers/assets.py`,
`src/api/schemas/assets.py`, migrations `a8b9c0d1e2f3` + `b9c0d1e2f3a4`.
Backend (modified): `src/core/orm.py`, `src/core/context_store.py`,
`src/core/safety.py`, `src/config.py`, `src/api/services/inventory_service.py`
(shim), `src/api/dependencies.py` (hoisted `require_tenant_permission`,
new `require_global_permission`), `src/api/app.py`,
`src/assessments/normalizers.py` (`passthrough`, `fortiedr.results`),
`src/utils/seed_context.py`, `pyproject.toml` (openpyxl; dev aiosqlite).
Frontend: `src/pages/assets/**`, `src/pages/global/GlobalAssetsPage.tsx`,
`src/hooks/useAssets.ts`, `src/api/{endpoints,types}.ts`,
`src/components/common/DataTable.tsx` (additive sorting),
`src/lib/utils.ts` (`downloadBlob`), `App.tsx`, sidebars, `Header.tsx`,
`src/pages/inventory/InventoryPage.tsx` (reduced to baselines/known changes).

Validation steps:

1. `alembic upgrade head` against a copy of the dev DB; verify asset counts
   vs blob components and spot-check an MCP-managed asset's columns.
2. `uv run pytest` — full self-contained suite (asset service/search,
   adapter regression, gateway-contract shim, import/export, enrichment
   engine, safety regression over the 2776-name baseline).
3. Manual API pass: create firewall asset with `mcp_connection` → device in
   gateway (token REDACTED) → auto enrichment run → discovered attributes +
   provenance → edit a field → re-enrich → `manual_wins` respected.
4. FortiEDR: managed `edr_console` → enrich → N `endpoint` subitems on
   the console (Sub-inventory tab + `subitems_summary` aggregate); the
   assets table stays endpoint-free; re-run is idempotent.
5. Export CSV/XLSX with filters; import dry-run → confirm.
6. Frontend: `/t/<id>/assets` list/filters/sort/detail/dynamic form;
   `/global/assets` as platform admin; permission gating.
7. Agent flow intact: run a test ticket (query_client_db returns the
   assembled inventory) and create an assessment (targets snapshot OK).
