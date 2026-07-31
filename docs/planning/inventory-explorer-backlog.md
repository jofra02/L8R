# Inventory Explorer — Follow-up Backlog

Deferred items from the 2026-07-30 hierarchical resource explorer refactor
(see `docs/assets.md` §Frontend). Each entry is self-contained.

## 1. App-wide DataTable → InventoryDataGrid migration

The inventory module runs on `src/components/grid/InventoryDataGrid.tsx`
(TanStack v8: resize/reorder/visibility/sticky/virtualization/keyboard).
The remaining ~9 `DataTable` consumers (Tickets, Runs, Assessments,
Audit, Notifications, Global pages, ProductCatalog) still use the legacy
`src/components/common/DataTable.tsx`. Migrating them removes the dual
table stack; blast radius is every non-inventory list page, so do it as
its own change with per-page manual verification. `DataTable` can be
deleted afterwards.

## 2. Relations Map view

Relations render as a table (SOURCE | RELATIONSHIP | TARGET | TYPE |
DIRECTION). The optional `Table | Map` toggle (topology graph) was
deferred — needs a layout engine decision (no graph lib in the bundle).

## 3. JSONB attribute filtering on subitems

The subitems list filters on relational columns only. `attr.<key>`
containment filters (as the assets list has, GIN-backed) would make the
discovered attribute columns server-filterable. Requires: whitelist
strategy for free-form keys (subitems have no declared schema),
`attributes` GIN index on `asset_subitems`.

## 4. FortiGate nested-pack conversion

`fortigate@2` maps interfaces/vdoms/ha/license as parent-asset attribute
blobs. Converting them to nested subitems (`vdom` → `interface` rules
with `parent:`) gives them presence tracking, per-level filtering and
drill-down — but changes live data semantics (attribute blobs disappear
from `attributes`, ClientContext consumers see subitems metadata
instead) and needs its own migration/comms. The engine/pack contract is
ready (`SubitemParent`, topo-sorted rules, scoped absence).

## 5. Full server-side export

`InventoryDataGrid`'s export button emits a client-side CSV of loaded
rows (server mode = current page). The assets list keeps its own full
server export (CSV/XLSX). A generic "export all matching rows"
server-side endpoint for subitems/history/sync-runs is pending.

## 6. Tenant-keyed react-query caches outside the inventory module

`useAssets.ts` keys are tenant-scoped (`["assets", <tenant>, ...]`).
Other hooks (`useTickets`, `useRuns`, `useAudit`, `useNotifications`,
`useAssessments`) still lack the tenant segment — a platform admin
switching `/t/<tenant>` shells can briefly see cached rows from the
previous tenant until refetch. Same fix pattern as
`useAssetScope()`.

## 7. Attribute sub-tab in the URL (`atab`)

The Attributes view's sub-tab (General / dataset / Raw) is
component-local state (survives tab switches via keep-mounted panels,
not refresh). Mirroring it to an `atab` query param would make deep
links land on a specific dataset.

## 8. License inventory follow-ups

The License tab (2026-07-31) normalizes FortiGate `/license/status` and
FortiEDR summary/organizations into `attributes.licenses`. Deferred:
license column in the assets list (worst-state chip + next expiry),
Overview license block, server-side expiry range filters, the
`fgt74_monitor_sys_get_vm_information` step (richer VM license detail),
expiry alerting/notifications, and a license assessment control
(support-contract/subscription expiry as an assessment rule — the
normalizer registry is shared, so the parser is already available there).

## 9. Scroll position restoration

Per-tab scroll restoration was scoped out ("when reasonable"). The
workspace store is the natural place (in-memory map keyed by
location.key).
