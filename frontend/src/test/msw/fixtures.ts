import type { Asset, AssetSubitem, AssetTypeDef } from "@/api/types";

/** Subitem row as the nested-subitems backend serves it (Phase 1 contract).
 * Extends the app type locally until the app type itself gains the fields. */
export type SubitemRow = AssetSubitem & {
  parent_subitem_id: string | null;
  children_count: number;
};

export function makeAsset(partial: Partial<Asset> & { id: string; name: string }): Asset {
  return {
    customer_id: "acme",
    ref: `AST-${partial.id}`,
    asset_type: "firewall",
    type_schema_version: 1,
    manufacturer: null,
    model: null,
    product_name: null,
    serial_number: null,
    location: null,
    owner: null,
    ip_address: null,
    fqdn: null,
    status: "active",
    criticality: null,
    tags: [],
    purchase_date: null,
    warranty_expires: null,
    eol_date: null,
    attributes: {},
    provenance: {},
    managed: false,
    mcp_config: null,
    sync_status: null,
    sync_error: null,
    last_synced_at: null,
    external_source: null,
    external_id: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    deleted_at: null,
    created_by: null,
    updated_by: null,
    ...partial,
  };
}

export function makeSubitem(
  partial: Partial<SubitemRow> & { id: string; parent_asset_id: string; name: string },
): SubitemRow {
  return {
    source: "fortiedr",
    kind: "endpoint",
    external_id: partial.id,
    state: "Running",
    attributes: {},
    absent: false,
    first_seen_at: "2026-07-01T00:00:00Z",
    last_seen_at: "2026-07-29T00:00:00Z",
    last_sync_run_id: null,
    promoted_asset_id: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-29T00:00:00Z",
    parent_subitem_id: null,
    children_count: 0,
    ...partial,
  };
}

export interface Fixtures {
  types: AssetTypeDef[];
  assets: Asset[];
  subitems: SubitemRow[];
}

function buildDefaults(): Fixtures {
  const types: AssetTypeDef[] = [
    {
      type_id: "firewall",
      version: 1,
      label: "Firewall",
      category: "network",
      roles: [],
      open_attributes: true,
      fields: [
        { key: "os_version", label: "OS version", type: "string", required: false, filterable: true, searchable: false, sensitive: false },
      ],
      relations: { allowed: ["depends_on", "connected_to", "managed_by", "member_of"] },
    },
    {
      type_id: "edr_console",
      version: 1,
      label: "EDR Console",
      category: "security",
      roles: [],
      open_attributes: true,
      fields: [],
      relations: { allowed: ["depends_on", "connected_to", "managed_by"] },
    },
  ];

  const assets: Asset[] = [
    makeAsset({
      id: "a-console",
      name: "FortiEDR Console",
      asset_type: "edr_console",
      product_name: "FortiEDR",
      managed: true,
      sync_status: "ok",
      subitems_summary: {
        endpoint: { total: 3, by_state: { Running: 2, Disconnected: 1 }, absent: 1 },
        interface: { total: 2, by_state: { Up: 1, Down: 1 }, absent: 0 },
      },
    }),
    makeAsset({
      id: "a-fw",
      name: "Branch Firewall",
      asset_type: "firewall",
      product_name: "FortiGate",
      model: "FGT60E",
      manufacturer: "Fortinet",
      ip_address: "10.0.0.1",
      criticality: "high",
      attributes: {
        os_version: "7.4.5",
        interfaces: [
          { name: "port1", status: "up", ip: "10.0.0.1" },
          { name: "port2", status: "down", ip: null },
        ],
      },
      provenance: { "attributes.interfaces": { source: "discovered" } },
    }),
    makeAsset({
      id: "a-plain",
      name: "Legacy Router",
      asset_type: "firewall",
      status: "retired",
    }),
  ];

  // a-console: 2 root endpoints; DC1 has two interface children (nested).
  const subitems: SubitemRow[] = [
    makeSubitem({
      id: "ep-dc1",
      parent_asset_id: "a-console",
      name: "DC1",
      external_id: "ext-dc1",
      attributes: { ip: "10.0.0.10", os: "Windows Server 2022" },
      children_count: 2,
    }),
    makeSubitem({
      id: "ep-ws2",
      parent_asset_id: "a-console",
      name: "WS2",
      external_id: "ext-ws2",
      state: "Disconnected",
      absent: true,
      attributes: { ip: "10.0.0.20", os: "Windows 11" },
    }),
    makeSubitem({
      id: "if-dc1-1",
      parent_asset_id: "a-console",
      parent_subitem_id: "ep-dc1",
      kind: "interface",
      name: "eth0",
      external_id: "ext-dc1-eth0",
      state: "Up",
      attributes: { mac: "00:11:22:33:44:55" },
    }),
    makeSubitem({
      id: "if-dc1-2",
      parent_asset_id: "a-console",
      parent_subitem_id: "ep-dc1",
      kind: "interface",
      name: "eth1",
      external_id: "ext-dc1-eth1",
      state: "Down",
      attributes: { mac: "00:11:22:33:44:66" },
    }),
  ];

  return { types, assets, subitems };
}

export const fixtures: Fixtures = buildDefaults();

export function resetFixtures(): void {
  const fresh = buildDefaults();
  fixtures.types = fresh.types;
  fixtures.assets = fresh.assets;
  fixtures.subitems = fresh.subitems;
}
