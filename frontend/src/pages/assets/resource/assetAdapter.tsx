import { useState } from "react";
import { Pencil, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import { StatusBadge } from "@/components/common/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import {
  useAsset,
  useAssetTypes,
  useDeleteAsset,
  useEnrichAsset,
  useRestoreAsset,
} from "@/hooks/useAssets";
import type { Asset, AssetTypeDef } from "@/api/types";
import { AssetFormModal } from "../AssetFormModal";
import { SmartAttributes } from "../attributes/SmartAttributes";
import { SyncStatusBadge } from "../SyncStatusBadge";
import { OverviewSection } from "../detail/OverviewSection";
import { LicenseSection } from "../detail/LicenseSection";
import { RelationsSection } from "../detail/RelationsSection";
import { SubInventorySection } from "../detail/SubInventorySection";
import { IntegrationSection } from "../detail/IntegrationSection";
import { HistorySection } from "../detail/HistorySection";
import { registerAdapter } from "./registry";
import type { ResourceAdapter, ResourceModel, ResourceRef, ViewContext } from "./types";

export interface AssetResource {
  asset: Asset;
  typeDef?: AssetTypeDef;
}

const VIEWS = [
  { id: "overview", label: "Overview" },
  { id: "attributes", label: "Attributes" },
  { id: "license", label: "License" },
  { id: "relations", label: "Relations" },
  { id: "sub-inventory", label: "Discovered inventory" },
  { id: "integration", label: "Integration" },
  { id: "history", label: "History" },
];

function hasLicenseData(asset: Asset): boolean {
  const a = asset.attributes;
  return (
    (Array.isArray(a["licenses"]) && a["licenses"].length > 0) ||
    a["license_status"] != null ||
    a["license_type"] != null ||
    a["license_expiration"] != null ||
    a["license_capacity"] != null
  );
}

function AssetActions({ model, onDeleted }: { model: ResourceModel<AssetResource>; onDeleted?: () => void }) {
  const { asset } = model.raw;
  const { hasPermission } = useAuth();
  const canWrite = hasPermission("assets:write");
  const canManage = hasPermission("assets:manage");

  const [editOpen, setEditOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const deleteMutation = useDeleteAsset();
  const restoreMutation = useRestoreAsset();
  const enrichMutation = useEnrichAsset();

  return (
    <div className="flex items-center gap-2 shrink-0">
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
              <button
                onClick={() => setDeleteConfirm(false)}
                className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                onClick={() =>
                  deleteMutation.mutate(asset.id, {
                    onSuccess: () => {
                      setDeleteConfirm(false);
                      onDeleted?.();
                    },
                  })
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

function RelationsView({ asset, ctx }: { asset: Asset; ctx: ViewContext }) {
  const { hasPermission } = useAuth();
  return (
    <RelationsSection
      asset={asset}
      canWrite={hasPermission("assets:write") && !asset.deleted_at}
      ctx={ctx}
    />
  );
}

export const assetAdapter: ResourceAdapter<AssetResource> = {
  type: "asset",

  useResource(ref: ResourceRef) {
    const { data: asset, isLoading, error } = useAsset(ref.id);
    const { data: types } = useAssetTypes();
    if (!asset) return { isLoading, error };
    const typeDef = types?.find((t) => t.type_id === asset.asset_type);
    const model: ResourceModel<AssetResource> = {
      ref,
      name: asset.name,
      typeLabel: typeDef?.label ?? asset.asset_type,
      deleted: !!asset.deleted_at,
      badges: (
        <>
          {asset.criticality && <StatusBadge value={asset.criticality} type="severity" />}
          <SyncStatusBadge asset={asset} />
          {asset.deleted_at && (
            <span className="text-xs px-2 py-0.5 rounded bg-severity-critical/15 text-severity-critical">
              deleted
            </span>
          )}
        </>
      ),
      metaLine: (
        <span className="font-mono">
          {asset.ref} · {asset.id}
        </span>
      ),
      ancestors: [{ label: "Assets", afterPath: "" }],
      raw: { asset, typeDef },
    };
    return { isLoading: false, model };
  },

  buildPath(ref, view) {
    return view && view !== "overview" ? `${ref.assetId}/${view}` : ref.assetId;
  },

  views(model) {
    // Capability-driven: License only appears when the asset carries
    // license data (normalized or raw).
    return VIEWS.filter((v) => v.id !== "license" || hasLicenseData(model.raw.asset));
  },

  renderView(view, model, ctx) {
    const { asset, typeDef } = model.raw;
    switch (view) {
      case "attributes":
        return <SmartAttributes asset={asset} typeDef={typeDef} ctx={ctx} />;
      case "license":
        return <LicenseSection asset={asset} ctx={ctx} />;
      case "relations":
        return <RelationsView asset={asset} ctx={ctx} />;
      case "sub-inventory":
        return <SubInventorySection assetId={asset.id} parentSubitemId="root" ctx={ctx} />;
      case "integration":
        return <IntegrationSection asset={asset} ctx={ctx} />;
      case "history":
        return <HistorySection assetId={asset.id} ctx={ctx} />;
      case "overview":
      default:
        return <OverviewSection asset={asset} />;
    }
  },

  Actions: AssetActions,
};

registerAdapter(assetAdapter);
