import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Pencil, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import { DataTable, type Column } from "@/components/common/DataTable";
import { EmptyState } from "@/components/common/EmptyState";
import { JsonViewer } from "@/components/common/JsonViewer";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { useAuth } from "@/hooks/useAuth";
import { usePagination } from "@/hooks/usePagination";
import { useTenantNavigate } from "@/hooks/useTenantNavigate";
import {
  useAsset,
  useAssetHistory,
  useAssetRelations,
  useAssets,
  useAssetSyncRuns,
  useAssetTypes,
  useCreateRelation,
  useDeleteAsset,
  useDeleteRelation,
  useEnrichAsset,
  useRestoreAsset,
} from "@/hooks/useAssets";
import type { Asset, AssetAuditEntry, AssetRelation, AssetSyncRun, AssetTypeDef } from "@/api/types";
import { AssetFormModal } from "./AssetFormModal";
import { SyncStatusBadge } from "./SyncStatusBadge";

const TABS = ["Overview", "Attributes", "Relations", "Integration", "History"] as const;
type Tab = (typeof TABS)[number];

export function AssetDetailPage() {
  const { assetId, tenantId } = useParams<{ assetId: string; tenantId: string }>();
  const navigate = useTenantNavigate();
  const { hasPermission } = useAuth();
  const canWrite = hasPermission("assets:write");
  const canManage = hasPermission("assets:manage");

  const { data: asset, isLoading } = useAsset(assetId);
  const { data: types } = useAssetTypes();
  const [tab, setTab] = useState<Tab>("Overview");
  const [editOpen, setEditOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const deleteMutation = useDeleteAsset();
  const restoreMutation = useRestoreAsset();
  const enrichMutation = useEnrichAsset();

  if (isLoading) return <LoadingSpinner className="py-16" />;
  if (!asset) return <EmptyState title="Not found" message="Asset not found" />;

  const typeDef = types?.find((t) => t.type_id === asset.asset_type);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <Link to={`/t/${tenantId}/assets`} className="text-text-secondary hover:text-text-primary">
            <ArrowLeft size={18} />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-semibold text-text-primary">{asset.name}</h1>
              <span className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary">
                {typeDef?.label ?? asset.asset_type}
              </span>
              {asset.criticality && <StatusBadge value={asset.criticality} type="severity" />}
              <SyncStatusBadge asset={asset} />
              {asset.deleted_at && (
                <span className="text-xs px-2 py-0.5 rounded bg-severity-critical/15 text-severity-critical">deleted</span>
              )}
            </div>
            <p className="text-xs text-text-muted font-mono mt-1">{asset.ref} · {asset.id}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {canManage && asset.managed && !asset.deleted_at && (
            <button
              onClick={() => enrichMutation.mutate(asset.id)}
              disabled={enrichMutation.isPending}
              className="flex items-center gap-2 bg-elevated border border-border hover:bg-card text-text-secondary text-sm px-3 py-2 rounded-md transition-colors disabled:opacity-50"
            >
              <RefreshCw size={16} /> Enrich now
            </button>
          )}
          {canManage && asset.deleted_at && (
            <button
              onClick={() => restoreMutation.mutate(asset.id)}
              className="flex items-center gap-2 bg-elevated border border-border hover:bg-card text-text-secondary text-sm px-3 py-2 rounded-md transition-colors"
            >
              <RotateCcw size={16} /> Restore
            </button>
          )}
          {canWrite && !asset.deleted_at && (
            <>
              <button
                onClick={() => setEditOpen(true)}
                className="flex items-center gap-2 bg-elevated border border-border hover:bg-card text-text-secondary text-sm px-3 py-2 rounded-md transition-colors"
              >
                <Pencil size={16} /> Edit
              </button>
              <button
                onClick={() => setDeleteConfirm(true)}
                className="flex items-center gap-2 bg-status-failed/20 text-status-failed border border-status-failed/30 text-sm px-3 py-2 rounded-md transition-colors"
              >
                <Trash2 size={16} /> Delete
              </button>
            </>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-border flex gap-0">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
              tab === t
                ? "border-accent text-text-primary"
                : "border-transparent text-text-muted hover:text-text-secondary"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Overview" && <OverviewTab asset={asset} />}
      {tab === "Attributes" && <AttributesTab asset={asset} typeDef={typeDef} />}
      {tab === "Relations" && <RelationsTab asset={asset} canWrite={canWrite && !asset.deleted_at} />}
      {tab === "Integration" && <IntegrationTab asset={asset} />}
      {tab === "History" && <HistoryTab assetId={asset.id} />}

      {editOpen && <AssetFormModal editing={asset} onClose={() => setEditOpen(false)} />}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-card border border-border rounded-lg w-full max-w-md shadow-xl p-5 space-y-4">
            <h2 className="text-sm font-semibold text-text-primary">Delete asset?</h2>
            <p className="text-sm text-text-secondary">
              "{asset.name}" is soft-deleted and can be restored later.
              {asset.managed && " The device is removed from the MCP gateway."}
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setDeleteConfirm(false)} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
                Cancel
              </button>
              <button
                onClick={() =>
                  deleteMutation.mutate(asset.id, { onSuccess: () => navigate("/assets") })
                }
                disabled={deleteMutation.isPending}
                className="px-4 py-2 bg-status-failed/20 text-status-failed border border-status-failed/30 text-sm rounded-md disabled:opacity-50"
              >
                {deleteMutation.isPending ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// --- Overview ---

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs text-text-muted">{label}</p>
      <p className="text-sm text-text-primary mt-0.5">{value ?? "—"}</p>
    </div>
  );
}

function OverviewTab({ asset }: { asset: Asset }) {
  return (
    <div className="bg-card border border-border rounded-lg p-5 grid grid-cols-3 gap-4">
      <Field label="Status" value={asset.status} />
      <Field label="Manufacturer" value={asset.manufacturer} />
      <Field label="Model" value={asset.model} />
      <Field label="Serial number" value={asset.serial_number && <span className="font-mono">{asset.serial_number}</span>} />
      <Field label="IP address" value={asset.ip_address && <span className="font-mono">{asset.ip_address}</span>} />
      <Field label="FQDN" value={asset.fqdn} />
      <Field label="Location" value={asset.location} />
      <Field label="Owner" value={asset.owner} />
      <Field
        label="Tags"
        value={asset.tags.length ? (
          <span className="flex flex-wrap gap-1">
            {asset.tags.map((t) => (
              <span key={t} className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary">{t}</span>
            ))}
          </span>
        ) : null}
      />
      <Field label="Purchase date" value={asset.purchase_date} />
      <Field label="Warranty expires" value={asset.warranty_expires} />
      <Field label="End of life" value={asset.eol_date} />
      <Field label="Created" value={<TimeAgo date={asset.created_at} />} />
      <Field label="Updated" value={<TimeAgo date={asset.updated_at} />} />
      <Field
        label="External identity"
        value={asset.external_id && (
          <span className="font-mono text-xs">{asset.external_source}:{asset.external_id}</span>
        )}
      />
    </div>
  );
}

// --- Attributes ---

function AttributesTab({ asset, typeDef }: { asset: Asset; typeDef?: AssetTypeDef }) {
  const entries = Object.entries(asset.attributes).filter(([k]) => k !== "legacy_role");
  if (entries.length === 0) return <EmptyState message="No attributes" />;
  const fieldLabel = (key: string) => typeDef?.fields.find((f) => f.key === key)?.label ?? key;
  const provenance = (key: string) => asset.provenance[`attributes.${key}`]?.source;

  return (
    <div className="bg-card border border-border rounded-lg divide-y divide-border-subtle">
      {entries.map(([key, value]) => (
        <div key={key} className="px-5 py-3 grid grid-cols-[240px_1fr_110px] gap-4 items-start">
          <p className="text-sm text-text-secondary">{fieldLabel(key)}</p>
          <div className="text-sm text-text-primary min-w-0">
            {typeof value === "object" && value !== null ? (
              <JsonViewer data={value} />
            ) : (
              <span className="break-all">{String(value)}</span>
            )}
          </div>
          <div className="text-right">
            {provenance(key) === "discovered" ? (
              <span className="text-xs px-2 py-0.5 rounded bg-accent/15 text-accent">discovered</span>
            ) : (
              <span className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-muted">manual</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// --- Relations ---

function RelationsTab({ asset, canWrite }: { asset: Asset; canWrite: boolean }) {
  const { data: relations, isLoading } = useAssetRelations(asset.id);
  const deleteMutation = useDeleteRelation();
  const [addOpen, setAddOpen] = useState(false);

  const columns: Column<AssetRelation>[] = [
    {
      key: "source",
      header: "Source",
      render: (r) => <span className={r.source_asset_id === asset.id ? "text-text-primary font-medium" : "text-text-secondary"}>{r.source_name ?? r.source_asset_id}</span>,
    },
    {
      key: "relation_type",
      header: "Relation",
      render: (r) => <span className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary">{r.relation_type}</span>,
      className: "w-36",
    },
    {
      key: "target",
      header: "Target",
      render: (r) => <span className={r.target_asset_id === asset.id ? "text-text-primary font-medium" : "text-text-secondary"}>{r.target_name ?? r.target_asset_id}</span>,
    },
    {
      key: "provenance",
      header: "Origin",
      render: (r) => <span className="text-xs text-text-muted">{r.provenance}</span>,
      className: "w-24",
    },
    {
      key: "actions",
      header: "",
      render: (r) =>
        canWrite ? (
          <button
            onClick={(e) => {
              (e as React.MouseEvent).stopPropagation();
              if (confirm("Remove this relation?")) deleteMutation.mutate(r.id);
            }}
            className="text-text-muted hover:text-status-failed transition-colors"
          >
            <Trash2 size={14} />
          </button>
        ) : null,
      className: "w-10",
    },
  ];

  return (
    <div className="space-y-3">
      {canWrite && (
        <div className="flex justify-end">
          <button
            onClick={() => setAddOpen(true)}
            className="bg-elevated border border-border hover:bg-card text-text-secondary text-sm px-3 py-1.5 rounded-md transition-colors"
          >
            Add relation
          </button>
        </div>
      )}
      <div className="bg-card border border-border rounded-lg">
        <DataTable columns={columns} data={relations ?? []} loading={isLoading} emptyMessage="No relations" />
      </div>
      {addOpen && <RelationModal asset={asset} onClose={() => setAddOpen(false)} />}
    </div>
  );
}

function RelationModal({ asset, onClose }: { asset: Asset; onClose: () => void }) {
  const [target, setTarget] = useState("");
  const [relationType, setRelationType] = useState("depends_on");
  const [direction, setDirection] = useState<"out" | "in">("out");
  const createMutation = useCreateRelation(asset.id);
  const { data: candidates } = useAssets({ page: 1, page_size: 100, sort: "name" });
  const { data: types } = useAssetTypes();
  const allowed = types?.find((t) => t.type_id === asset.asset_type)?.relations.allowed ?? [];
  const relationOptions = allowed.length ? allowed : ["depends_on", "connected_to", "managed_by", "member_of"];

  const inputClass =
    "w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-md shadow-xl">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">Add Relation</h2>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate(
              { target_asset_id: target, relation_type: relationType, direction },
              { onSuccess: onClose },
            );
          }}
          className="p-5 space-y-4"
        >
          <div>
            <label className="block text-xs text-text-secondary mb-1">Direction</label>
            <select value={direction} onChange={(e) => setDirection(e.target.value as "out" | "in")} className={inputClass}>
              <option value="out">{asset.name} → other</option>
              <option value="in">other → {asset.name}</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Relation type</label>
            <select value={relationType} onChange={(e) => setRelationType(e.target.value)} className={inputClass}>
              {relationOptions.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Other asset</label>
            <select value={target} onChange={(e) => setTarget(e.target.value)} required className={inputClass}>
              <option value="">Select asset...</option>
              {candidates?.items.filter((a) => a.id !== asset.id).map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
              Cancel
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending || !target}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50"
            >
              {createMutation.isPending ? "Saving..." : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// --- Integration (MCP + sync runs) ---

function IntegrationTab({ asset }: { asset: Asset }) {
  const { page, pageSize, setPage } = usePagination();
  const { data: runs, isLoading } = useAssetSyncRuns(asset.id, page, pageSize);
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!asset.managed) {
    return <EmptyState title="Not managed" message="Enable 'MCP managed device' on this asset to connect it to the gateway." />;
  }
  const cfg = asset.mcp_config ?? {};

  const columns: Column<AssetSyncRun>[] = [
    {
      key: "created_at",
      header: "Queued",
      render: (r) => <TimeAgo date={r.created_at} />,
      className: "w-32",
    },
    {
      key: "pack",
      header: "Pack",
      render: (r) => <span className="font-mono text-xs text-text-secondary">{r.pack_id}@{r.pack_version}</span>,
      className: "w-32",
    },
    {
      key: "trigger",
      header: "Trigger",
      render: (r) => <span className="text-xs text-text-secondary">{r.trigger}</span>,
      className: "w-24",
    },
    {
      key: "status",
      header: "Status",
      render: (r) => <StatusBadge value={r.status === "completed_with_errors" ? "completed" : r.status} type="status" />,
      className: "w-32",
    },
    {
      key: "result",
      header: "Result",
      render: (r) => {
        const s = r.stats ?? {};
        if (r.status === "failed") return <span className="text-xs text-status-failed">{r.error ?? "failed"}</span>;
        return (
          <span className="text-xs text-text-secondary">
            {String(s["assets_created"] ?? 0)} created · {String(s["assets_updated"] ?? 0)} updated
            {r.status === "completed_with_errors" ? " · with errors" : ""}
          </span>
        );
      },
    },
    {
      key: "expand",
      header: "",
      render: (r) => (
        <button
          onClick={(e) => {
            (e as React.MouseEvent).stopPropagation();
            setExpanded(expanded === r.id ? null : r.id);
          }}
          className="text-xs text-accent hover:underline"
        >
          {expanded === r.id ? "Hide" : "Details"}
        </button>
      ),
      className: "w-16",
    },
  ];

  const expandedRun = runs?.items.find((r) => r.id === expanded);

  return (
    <div className="space-y-4">
      <div className="bg-card border border-border rounded-lg p-5 grid grid-cols-3 gap-4">
        <Field label="Appliance" value={`${cfg["vendor"] ?? "?"} / ${cfg["appliance"] ?? "?"}`} />
        <Field label="Device type" value={String(cfg["device_type"] ?? "—")} />
        <Field label="OS version" value={String(cfg["os_version"] ?? "—")} />
        <Field label="Host" value={<span className="font-mono">{String(cfg["host"] ?? "—")}:{String(cfg["port"] ?? "")}</span>} />
        <Field label="Sync status" value={<SyncStatusBadge asset={asset} />} />
        <Field label="Last synced" value={asset.last_synced_at ? <TimeAgo date={asset.last_synced_at} /> : "—"} />
        {asset.sync_error && (
          <div className="col-span-3 border border-status-failed/30 bg-status-failed/10 rounded-md p-3 text-sm text-status-failed">
            {asset.sync_error}
          </div>
        )}
        {(cfg["sync_warnings"] as string[] | undefined)?.map((w) => (
          <div key={w} className="col-span-3 border border-severity-medium/30 bg-severity-medium/10 rounded-md p-3 text-sm text-severity-medium">
            {w}
          </div>
        ))}
      </div>

      <div className="bg-card border border-border rounded-lg">
        <DataTable
          columns={columns}
          data={runs?.items ?? []}
          loading={isLoading}
          page={page}
          totalPages={runs?.total_pages}
          total={runs?.total}
          onPageChange={setPage}
          emptyMessage="No enrichment runs yet"
        />
        {expandedRun && (
          <div className="border-t border-border p-4">
            <JsonViewer data={expandedRun.stats} defaultExpanded />
          </div>
        )}
      </div>
    </div>
  );
}

// --- History ---

function HistoryTab({ assetId }: { assetId: string }) {
  const { page, pageSize, setPage } = usePagination();
  const { data, isLoading } = useAssetHistory(assetId, page, pageSize);
  const [expanded, setExpanded] = useState<number | null>(null);

  const columns: Column<AssetAuditEntry>[] = [
    {
      key: "created_at",
      header: "When",
      render: (r) => <TimeAgo date={r.created_at} />,
      className: "w-32",
    },
    {
      key: "action",
      header: "Action",
      render: (r) => <span className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary">{r.action}</span>,
      className: "w-40",
    },
    {
      key: "actor",
      header: "Actor",
      render: (r) => <span className="font-mono text-xs text-text-secondary">{r.actor}</span>,
    },
    {
      key: "expand",
      header: "",
      render: (r) => (
        <button
          onClick={(e) => {
            (e as React.MouseEvent).stopPropagation();
            setExpanded(expanded === r.id ? null : r.id);
          }}
          className="text-xs text-accent hover:underline"
        >
          {expanded === r.id ? "Hide" : "Changes"}
        </button>
      ),
      className: "w-20",
    },
  ];

  const expandedEntry = data?.items.find((r) => r.id === expanded);

  return (
    <div className="bg-card border border-border rounded-lg">
      <DataTable
        columns={columns}
        data={data?.items ?? []}
        loading={isLoading}
        page={page}
        totalPages={data?.total_pages}
        total={data?.total}
        onPageChange={setPage}
        emptyMessage="No history"
      />
      {expandedEntry && (
        <div className="border-t border-border p-4">
          <JsonViewer data={expandedEntry.changes} defaultExpanded />
        </div>
      )}
    </div>
  );
}
