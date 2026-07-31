import { useMemo, useState } from "react";
import { Trash2 } from "lucide-react";
import { InventoryDataGrid } from "@/components/grid/InventoryDataGrid";
import type { GridColumnSchema } from "@/components/grid/types";
import {
  useAssetRelations,
  useAssets,
  useAssetTypes,
  useCreateRelation,
  useDeleteRelation,
} from "@/hooks/useAssets";
import type { Asset, AssetRelation } from "@/api/types";
import { useSyncedGridState } from "../workspace/store";
import { useWorkspace } from "../workspace/WorkspaceContext";
import type { ViewContext } from "../resource/types";

interface RelationsSectionProps {
  asset: Asset;
  canWrite: boolean;
  ctx: ViewContext;
}

export function RelationsSection({ asset, canWrite, ctx }: RelationsSectionProps) {
  const { openAsset } = useWorkspace();
  const { data: relations, isLoading, error, refetch } = useAssetRelations(asset.id);
  const deleteMutation = useDeleteRelation();
  const [addOpen, setAddOpen] = useState(false);
  const [gridState, setGridState] = useSyncedGridState(`${ctx.stateKeyPrefix}|relations`, false, {
    pageSize: 50,
  });

  const endpointCell = (id: string, name: string | null | undefined) => {
    const self = id === asset.id;
    if (self) return <span className="text-text-primary font-medium">{name ?? id}</span>;
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          openAsset(id);
        }}
        className="text-text-secondary hover:text-accent hover:underline"
      >
        {name ?? id}
      </button>
    );
  };

  const columns = useMemo<GridColumnSchema<AssetRelation>[]>(
    () => [
      {
        key: "source",
        header: "Source",
        sortable: true,
        filterable: true,
        width: 220,
        accessor: (r) => r.source_name ?? r.source_asset_id,
        render: (r) => endpointCell(r.source_asset_id, r.source_name),
      },
      {
        key: "relation_type",
        header: "Relationship",
        type: "badge",
        sortable: true,
        filterable: true,
        width: 140,
      },
      {
        key: "target",
        header: "Target",
        sortable: true,
        filterable: true,
        width: 220,
        accessor: (r) => r.target_name ?? r.target_asset_id,
        render: (r) => endpointCell(r.target_asset_id, r.target_name),
      },
      { key: "provenance", header: "Type", type: "badge", sortable: true, filterable: true, width: 110 },
      {
        key: "direction",
        header: "Direction",
        filterable: true,
        width: 100,
        accessor: (r) => (r.source_asset_id === asset.id ? "outbound" : "inbound"),
        render: (r) => (
          <span className="text-xs text-text-muted">
            {r.source_asset_id === asset.id ? "outbound" : "inbound"}
          </span>
        ),
      },
      {
        key: "actions",
        header: "",
        width: 50,
        render: (r) =>
          canWrite ? (
            <button
              type="button"
              title="Remove relation"
              onClick={(e) => {
                e.stopPropagation();
                if (confirm("Remove this relation?")) deleteMutation.mutate(r.id);
              }}
              className="text-text-muted hover:text-status-failed transition-colors"
            >
              <Trash2 size={14} />
            </button>
          ) : null,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [asset.id, canWrite],
  );

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
        <InventoryDataGrid<AssetRelation>
          gridId="asset.relations"
          columns={columns}
          data={relations ?? []}
          mode="client"
          state={gridState}
          onStateChange={setGridState}
          loading={isLoading}
          error={error ?? undefined}
          onRetry={() => refetch()}
          getRowId={(r) => String(r.id)}
          emptyMessage="No relations"
        />
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
