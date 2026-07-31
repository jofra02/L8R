import { useMemo, useState } from "react";
import { Drawer } from "@/components/common/Drawer";
import { JsonViewer } from "@/components/common/JsonViewer";
import { InventoryDataGrid } from "@/components/grid/InventoryDataGrid";
import type { GridColumnSchema } from "@/components/grid/types";
import { useAssetHistory } from "@/hooks/useAssets";
import type { AssetAuditEntry } from "@/api/types";
import { useSyncedGridState } from "../workspace/store";
import type { ViewContext } from "../resource/types";

interface HistorySectionProps {
  assetId: string;
  ctx: ViewContext;
}

export function HistorySection({ assetId, ctx }: HistorySectionProps) {
  const [gridState, setGridState] = useSyncedGridState(`${ctx.stateKeyPrefix}|history`, false, {});
  const { data, isLoading, error, refetch } = useAssetHistory(
    assetId,
    gridState.page,
    gridState.pageSize,
  );
  const [inspect, setInspect] = useState<AssetAuditEntry | null>(null);

  const columns = useMemo<GridColumnSchema<AssetAuditEntry>[]>(
    () => [
      { key: "created_at", header: "Timestamp", type: "timeago", width: 130 },
      { key: "action", header: "Action", type: "badge", width: 150 },
      { key: "actor", header: "Actor", type: "code", width: 200 },
      {
        key: "source",
        header: "Source",
        type: "badge",
        width: 110,
        accessor: (r) => (r.sync_run_id ? "enrichment" : "manual"),
      },
      {
        key: "changes",
        header: "Changes",
        width: 160,
        render: (r) => {
          const n = Object.keys(r.changes ?? {}).length;
          if (n === 0) return <span className="text-text-muted">—</span>;
          return (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setInspect(r);
              }}
              className="text-xs text-accent hover:underline"
            >
              {n} field{n === 1 ? "" : "s"}
            </button>
          );
        },
      },
    ],
    [],
  );

  return (
    <div className="bg-card border border-border rounded-lg">
      <InventoryDataGrid<AssetAuditEntry>
        gridId="asset.history"
        columns={columns}
        data={data?.items ?? []}
        mode="server"
        state={gridState}
        onStateChange={setGridState}
        total={data?.total}
        loading={isLoading}
        error={error ?? undefined}
        onRetry={() => refetch()}
        getRowId={(r) => String(r.id)}
        onOpen={(r) => setInspect(r)}
        emptyMessage="No history"
      />
      {inspect && (
        <Drawer title={`${inspect.action} — ${inspect.actor}`} onClose={() => setInspect(null)}>
          <JsonViewer data={inspect.changes} defaultExpanded controls />
        </Drawer>
      )}
    </div>
  );
}
