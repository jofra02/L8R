import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { DataTable, type Column } from "@/components/common/DataTable";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { usePagination } from "@/hooks/usePagination";
import { useAssetTypes, useGlobalAssets } from "@/hooks/useAssets";
import { listTenants } from "@/api/endpoints";
import type { Asset } from "@/api/types";
import { SyncStatusBadge } from "@/pages/assets/SyncStatusBadge";

const ASSET_STATUS_OPTIONS = ["active", "inactive", "maintenance", "retired"];

const selectClass =
  "bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent";

export function GlobalAssetsPage() {
  const navigate = useNavigate();
  const { page, pageSize, setPage, reset } = usePagination();
  const [tenant, setTenant] = useState("");
  const [assetType, setAssetType] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("-created_at");

  const filters = {
    page,
    page_size: pageSize,
    sort,
    ...(tenant && { tenant }),
    ...(assetType && { asset_type: assetType }),
    ...(status && { status }),
    ...(search && { q: search }),
  };

  const { data, isLoading } = useGlobalAssets(filters);
  const { data: types } = useAssetTypes();
  const { data: tenants } = useQuery({ queryKey: ["tenants"], queryFn: listTenants });

  const columns: Column<Asset>[] = [
    {
      key: "tenant",
      header: "Tenant",
      render: (r) => (
        <span className="font-mono text-xs px-2 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/30">
          {r.customer_id}
        </span>
      ),
      className: "w-36",
    },
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
      <h1 className="text-lg font-semibold text-text-primary">Global Assets</h1>

      <div className="flex flex-wrap gap-3">
        <select value={tenant} onChange={(e) => { setTenant(e.target.value); reset(); }} className={selectClass}>
          <option value="">All Tenants</option>
          {tenants?.map((t) => (
            <option key={t.customer_id} value={t.customer_id}>{t.name || t.customer_id}</option>
          ))}
        </select>
        <select value={assetType} onChange={(e) => { setAssetType(e.target.value); reset(); }} className={selectClass}>
          <option value="">All Types</option>
          {types?.map((t) => <option key={t.type_id} value={t.type_id}>{t.label}</option>)}
        </select>
        <select value={status} onChange={(e) => { setStatus(e.target.value); reset(); }} className={selectClass}>
          <option value="">All Statuses</option>
          {ASSET_STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
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
          onRowClick={(r) => navigate(`/t/${r.customer_id}/assets/${r.id}`)}
          emptyMessage="No assets found"
          sortKey={sort}
          onSortChange={(s) => { setSort(s); reset(); }}
        />
      </div>
    </div>
  );
}
