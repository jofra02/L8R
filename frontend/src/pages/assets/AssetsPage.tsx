import { useState } from "react";
import { Download, Plus, Upload } from "lucide-react";
import { toast } from "sonner";
import { DataTable, type Column } from "@/components/common/DataTable";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { useAuth } from "@/hooks/useAuth";
import { usePagination } from "@/hooks/usePagination";
import { useAssets, useAssetTypes } from "@/hooks/useAssets";
import { useTenantNavigate } from "@/hooks/useTenantNavigate";
import { exportAssets } from "@/api/endpoints";
import { downloadBlob } from "@/lib/utils";
import type { Asset } from "@/api/types";
import { AssetFormModal } from "./AssetFormModal";
import { ImportModal } from "./ImportModal";
import { SyncStatusBadge } from "./SyncStatusBadge";

const ASSET_STATUS_OPTIONS = ["active", "inactive", "maintenance", "retired"];
const CRITICALITY_OPTIONS = ["low", "medium", "high", "critical"];

const selectClass =
  "bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent";

export function AssetsPage() {
  const navigate = useTenantNavigate();
  const { hasPermission } = useAuth();
  const canWrite = hasPermission("assets:write");
  const canManage = hasPermission("assets:manage");

  const { page, pageSize, setPage, reset } = usePagination();
  const [assetType, setAssetType] = useState("");
  const [status, setStatus] = useState("");
  const [criticality, setCriticality] = useState("");
  const [managed, setManaged] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("-created_at");
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const filters = {
    page,
    page_size: pageSize,
    sort,
    ...(assetType && { asset_type: assetType }),
    ...(status && { status }),
    ...(criticality && { criticality }),
    ...(managed && { managed: managed === "managed" }),
    ...(search && { q: search }),
  };

  const { data, isLoading } = useAssets(filters);
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

  const columns: Column<Asset>[] = [
    {
      key: "name",
      header: "Name",
      sortable: true,
      render: (r) => (
        <div>
          <p className="text-text-primary font-medium">{r.name}</p>
          <p className="text-xs text-text-muted font-mono">{r.ref}</p>
        </div>
      ),
    },
    {
      key: "asset_type",
      header: "Type",
      sortable: true,
      render: (r) => (
        <span className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary">
          {types?.find((t) => t.type_id === r.asset_type)?.label ?? r.asset_type}
        </span>
      ),
      className: "w-32",
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      render: (r) => <span className="text-xs text-text-secondary">{r.status}</span>,
      className: "w-24",
    },
    {
      key: "criticality",
      header: "Criticality",
      sortable: true,
      render: (r) => (r.criticality ? <StatusBadge value={r.criticality} type="severity" /> : <span className="text-text-muted">—</span>),
      className: "w-28",
    },
    {
      key: "ip_address",
      header: "IP",
      sortable: true,
      render: (r) => <span className="font-mono text-xs text-text-secondary">{r.ip_address ?? "—"}</span>,
      className: "w-32",
    },
    {
      key: "serial_number",
      header: "Serial",
      sortable: true,
      render: (r) => <span className="font-mono text-xs text-text-secondary">{r.serial_number ?? "—"}</span>,
      className: "w-36",
    },
    {
      key: "mcp",
      header: "MCP",
      render: (r) => <SyncStatusBadge asset={r} />,
      className: "w-32",
    },
    {
      key: "updated_at",
      header: "Updated",
      sortable: true,
      render: (r) => <TimeAgo date={r.updated_at} />,
      className: "w-32",
    },
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

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select value={assetType} onChange={(e) => { setAssetType(e.target.value); reset(); }} className={selectClass}>
          <option value="">All Types</option>
          {types?.map((t) => (
            <option key={t.type_id} value={t.type_id}>{t.label}</option>
          ))}
        </select>
        <select value={status} onChange={(e) => { setStatus(e.target.value); reset(); }} className={selectClass}>
          <option value="">All Statuses</option>
          {ASSET_STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={criticality} onChange={(e) => { setCriticality(e.target.value); reset(); }} className={selectClass}>
          <option value="">All Criticalities</option>
          {CRITICALITY_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={managed} onChange={(e) => { setManaged(e.target.value); reset(); }} className={selectClass}>
          <option value="">MCP: all</option>
          <option value="managed">MCP managed</option>
          <option value="unmanaged">Not managed</option>
        </select>
        <input
          type="text"
          value={search}
          onChange={(e) => { setSearch(e.target.value); reset(); }}
          placeholder="Search name, ref, serial, IP..."
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent w-64"
        />
      </div>

      <div className="bg-card border border-border rounded-lg">
        <DataTable
          columns={columns}
          data={data?.items ?? []}
          loading={isLoading}
          page={page}
          totalPages={data?.total_pages}
          total={data?.total}
          onPageChange={setPage}
          onRowClick={(r) => navigate(`/assets/${r.id}`)}
          emptyMessage="No assets found"
          sortKey={sort}
          onSortChange={(s) => { setSort(s); reset(); }}
        />
      </div>

      {createOpen && <AssetFormModal onClose={() => setCreateOpen(false)} />}
      {importOpen && <ImportModal onClose={() => setImportOpen(false)} />}
    </div>
  );
}
