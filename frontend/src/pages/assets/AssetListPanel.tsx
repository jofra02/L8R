import { useState } from "react";
import { Copy, Download, ExternalLink, Plus, Upload } from "lucide-react";
import { toast } from "sonner";
import { InventoryDataGrid } from "@/components/grid/InventoryDataGrid";
import { DEFAULT_GRID_STATE, type GridColumnSchema, type GridState } from "@/components/grid/types";
import { StatusBadge } from "@/components/common/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { useAssets, useAssetTypes } from "@/hooks/useAssets";
import { exportAssets } from "@/api/endpoints";
import { downloadBlob } from "@/lib/utils";
import { serializeFilters } from "@/lib/columnFilters";
import type { Asset } from "@/api/types";
import { AssetFormModal } from "./AssetFormModal";
import { ImportModal } from "./ImportModal";
import { SyncStatusBadge } from "./SyncStatusBadge";

const selectClass =
  "bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent";

interface AssetListPanelProps {
  onOpenAsset: (asset: Asset) => void;
  /** "Open in new tab" context action; omitted → the entry is hidden. */
  onOpenAssetNewTab?: (asset: Asset) => void;
  /** Controlled grid state (workspace URL/store sync); omitted → local. */
  gridState?: GridState;
  onGridStateChange?: (next: GridState) => void;
}

export function AssetListPanel({
  onOpenAsset,
  onOpenAssetNewTab,
  gridState: controlledState,
  onGridStateChange,
}: AssetListPanelProps) {
  const { hasPermission } = useAuth();
  const canWrite = hasPermission("assets:write");
  const canManage = hasPermission("assets:manage");

  const [localState, setLocalState] = useState<GridState>({
    ...DEFAULT_GRID_STATE,
    sort: "-created_at",
  });
  const gridState = controlledState ?? localState;
  const setGridState = onGridStateChange ?? setLocalState;
  const [managed, setManaged] = useState("");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const filters = {
    page: gridState.page,
    page_size: gridState.pageSize,
    sort: gridState.sort,
    ...(managed && { managed: managed === "managed" }),
    ...(search && { q: search }),
    ...serializeFilters(gridState.filters),
  };

  const { data, isLoading, error, refetch } = useAssets(filters);
  const { data: types } = useAssetTypes();

  const handleExport = async (format: "csv" | "xlsx") => {
    setExporting(true);
    try {
      const { page: _p, page_size: _ps, ...exportFilters } = filters;
      const blob = await exportAssets(format, exportFilters);
      downloadBlob(blob, `assets.${format}`);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Export failed");
    } finally {
      setExporting(false);
    }
  };

  const columns: GridColumnSchema<Asset>[] = [
    {
      key: "name",
      header: "Name",
      sortable: true,
      filterable: true,
      primary: true,
      width: 280,
      accessor: (r) => r.name,
      render: (r) => (
        <div className="min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <p className="text-text-primary font-medium truncate hover:text-accent">{r.name}</p>
            {Object.entries(r.subitems_summary ?? {}).map(([kind, s]) => (
              <span
                key={kind}
                className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary whitespace-nowrap shrink-0"
                title={Object.entries(s.by_state)
                  .map(([state, n]) => `${state}: ${n}`)
                  .join(" · ")}
              >
                {s.total} {kind}
                {s.total === 1 ? "" : "s"}
              </span>
            ))}
          </div>
          <p className="text-xs text-text-muted font-mono truncate">{r.ref}</p>
        </div>
      ),
    },
    {
      key: "asset_type",
      header: "Type",
      sortable: true,
      filterable: true,
      width: 130,
      accessor: (r) => r.asset_type,
      render: (r) => (
        <span className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary whitespace-nowrap">
          {types?.find((t) => t.type_id === r.asset_type)?.label ?? r.asset_type}
        </span>
      ),
    },
    { key: "product_name", header: "Product", sortable: true, filterable: true, width: 130 },
    { key: "model", header: "Model", sortable: true, filterable: true, width: 120 },
    { key: "status", header: "Status", type: "badge", sortable: true, filterable: true, width: 100 },
    {
      key: "criticality",
      header: "Criticality",
      sortable: true,
      filterable: true,
      width: 110,
      render: (r) =>
        r.criticality ? (
          <StatusBadge value={r.criticality} type="severity" />
        ) : (
          <span className="text-text-muted">—</span>
        ),
    },
    { key: "ip_address", header: "IP", type: "code", sortable: true, filterable: true, width: 130 },
    {
      key: "serial_number",
      header: "Serial",
      type: "code",
      sortable: true,
      filterable: true,
      width: 150,
    },
    {
      key: "mcp",
      header: "MCP",
      width: 130,
      accessor: (r) => r.sync_status ?? (r.managed ? "managed" : ""),
      render: (r) => <SyncStatusBadge asset={r} />,
    },
    { key: "updated_at", header: "Updated", type: "timeago", sortable: true, width: 120 },
    { key: "manufacturer", header: "Manufacturer", sortable: true, filterable: true, width: 130, defaultHidden: true },
    { key: "location", header: "Location", width: 130, defaultHidden: true },
    { key: "owner", header: "Owner", filterable: true, width: 130, defaultHidden: true },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Assets</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => handleExport("csv")}
            disabled={exporting}
            className="flex items-center gap-2 bg-elevated border border-border hover:bg-card text-text-secondary text-sm px-3 py-2 rounded-md transition-colors disabled:opacity-50"
          >
            <Download size={16} /> CSV
          </button>
          <button
            onClick={() => handleExport("xlsx")}
            disabled={exporting}
            className="flex items-center gap-2 bg-elevated border border-border hover:bg-card text-text-secondary text-sm px-3 py-2 rounded-md transition-colors disabled:opacity-50"
          >
            <Download size={16} /> Excel
          </button>
          {canManage && (
            <button
              onClick={() => setImportOpen(true)}
              className="flex items-center gap-2 bg-elevated border border-border hover:bg-card text-text-secondary text-sm px-3 py-2 rounded-md transition-colors"
            >
              <Upload size={16} /> Import
            </button>
          )}
          {canWrite && (
            <button
              onClick={() => setCreateOpen(true)}
              className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors"
            >
              <Plus size={16} /> Add Asset
            </button>
          )}
        </div>
      </div>

      <div className="bg-card border border-border rounded-lg">
        <InventoryDataGrid<Asset>
          gridId="assets.list"
          columns={columns}
          data={data?.items ?? []}
          mode="server"
          state={gridState}
          onStateChange={setGridState}
          total={data?.total}
          loading={isLoading}
          error={error ?? undefined}
          onRetry={() => refetch()}
          getRowId={(r) => r.id}
          selectedRowId={selectedId}
          onSelect={(r) => setSelectedId(r ? r.id : null)}
          onOpen={onOpenAsset}
          emptyMessage="No assets found"
          contextMenuItems={(r) => [
            { label: "Open", icon: <ExternalLink size={13} />, onSelect: () => onOpenAsset(r) },
            ...(onOpenAssetNewTab
              ? [
                  {
                    label: "Open in new tab",
                    icon: <ExternalLink size={13} />,
                    onSelect: () => onOpenAssetNewTab(r),
                  },
                ]
              : []),
            {
              label: "Copy ID",
              icon: <Copy size={13} />,
              onSelect: () => {
                navigator.clipboard.writeText(r.id).then(
                  () => toast.success("Asset ID copied"),
                  () => toast.error("Copy failed"),
                );
              },
            },
          ]}
          quickFilters={
            <>
              <select
                value={managed}
                onChange={(e) => {
                  setManaged(e.target.value);
                  setGridState({ ...gridState, page: 1 });
                }}
                className={selectClass}
              >
                <option value="">MCP: all</option>
                <option value="managed">MCP managed</option>
                <option value="unmanaged">Not managed</option>
              </select>
              <input
                type="text"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setGridState({ ...gridState, page: 1 });
                }}
                placeholder="Search name, ref, serial, IP..."
                className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent w-64"
              />
            </>
          }
        />
      </div>

      {createOpen && <AssetFormModal onClose={() => setCreateOpen(false)} />}
      {importOpen && <ImportModal onClose={() => setImportOpen(false)} />}
    </div>
  );
}
