import { useMemo, useState } from "react";
import { Drawer } from "@/components/common/Drawer";
import { EmptyState } from "@/components/common/EmptyState";
import { JsonViewer } from "@/components/common/JsonViewer";
import { PropertyGrid } from "@/components/common/PropertyGrid";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { InventoryDataGrid } from "@/components/grid/InventoryDataGrid";
import type { GridColumnSchema } from "@/components/grid/types";
import { useAssetSyncRuns } from "@/hooks/useAssets";
import type { Asset, AssetSyncRun } from "@/api/types";
import { SyncStatusBadge } from "../SyncStatusBadge";
import { useSyncedGridState } from "../workspace/store";
import type { ViewContext } from "../resource/types";

interface IntegrationSectionProps {
  asset: Asset;
  ctx: ViewContext;
}

export function IntegrationSection({ asset, ctx }: IntegrationSectionProps) {
  const [gridState, setGridState] = useSyncedGridState(`${ctx.stateKeyPrefix}|integration`, false, {});
  const { data: runs, isLoading, error, refetch } = useAssetSyncRuns(
    asset.id,
    gridState.page,
    gridState.pageSize,
  );
  const [inspectRun, setInspectRun] = useState<AssetSyncRun | null>(null);

  const columns = useMemo<GridColumnSchema<AssetSyncRun>[]>(
    () => [
      { key: "created_at", header: "Queued", type: "timeago", width: 120 },
      {
        key: "pack",
        header: "Pack",
        type: "code",
        width: 130,
        accessor: (r) => `${r.pack_id}@${r.pack_version}`,
      },
      { key: "trigger", header: "Trigger", type: "badge", width: 100 },
      {
        key: "status",
        header: "Status",
        width: 120,
        render: (r) => (
          <StatusBadge value={r.status === "completed_with_errors" ? "completed" : r.status} type="status" />
        ),
      },
      {
        key: "result",
        header: "Result",
        width: 280,
        render: (r) => {
          const s = r.stats ?? {};
          if (r.status === "failed") {
            return <span className="text-xs text-status-failed truncate">{r.error ?? "failed"}</span>;
          }
          // Historical runs (pack produces era) report assets_created instead
          const created = s["subitems_created"] ?? s["assets_created"] ?? 0;
          const updated = s["subitems_updated"] ?? 0;
          const absent = s["subitems_absent"] ?? 0;
          return (
            <span className="text-xs text-text-secondary">
              {String(created)} discovered · {String(updated)} updated
              {Number(absent) > 0 ? ` · ${String(absent)} absent` : ""}
              {r.status === "completed_with_errors" ? " · with errors" : ""}
            </span>
          );
        },
      },
      {
        key: "details",
        header: "",
        width: 70,
        render: (r) => (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setInspectRun(r);
            }}
            className="text-xs text-accent hover:underline"
          >
            Details
          </button>
        ),
      },
    ],
    [],
  );

  if (!asset.managed) {
    return (
      <EmptyState
        title="Not managed"
        message="Enable 'MCP managed device' on this asset to connect it to the gateway."
      />
    );
  }
  const cfg = asset.mcp_config ?? {};
  const warnings = (cfg["sync_warnings"] as string[] | undefined) ?? [];

  return (
    <div className="space-y-4">
      <div className="bg-card border border-border rounded-lg px-5 py-2">
        <PropertyGrid
          items={[
            { label: "Appliance", value: `${cfg["vendor"] ?? "?"} / ${cfg["appliance"] ?? "?"}` },
            { label: "Device type", value: String(cfg["device_type"] ?? "—") },
            { label: "OS version", value: String(cfg["os_version"] ?? "—") },
            {
              label: "Host",
              value: (
                <span className="font-mono text-xs">
                  {String(cfg["host"] ?? "—")}:{String(cfg["port"] ?? "")}
                </span>
              ),
            },
            { label: "Sync status", value: <SyncStatusBadge asset={asset} /> },
            {
              label: "Last synced",
              value: asset.last_synced_at ? <TimeAgo date={asset.last_synced_at} /> : "—",
            },
          ]}
        />
        {asset.sync_error && (
          <div className="my-3 border border-status-failed/30 bg-status-failed/10 rounded-md p-3 text-sm text-status-failed">
            {asset.sync_error}
          </div>
        )}
        {warnings.map((w) => (
          <div
            key={w}
            className="my-3 border border-severity-medium/30 bg-severity-medium/10 rounded-md p-3 text-sm text-severity-medium"
          >
            {w}
          </div>
        ))}
      </div>

      <div className="bg-card border border-border rounded-lg">
        <InventoryDataGrid<AssetSyncRun>
          gridId="asset.sync-runs"
          columns={columns}
          data={runs?.items ?? []}
          mode="server"
          state={gridState}
          onStateChange={setGridState}
          total={runs?.total}
          loading={isLoading}
          error={error ?? undefined}
          onRetry={() => refetch()}
          getRowId={(r) => r.id}
          onOpen={(r) => setInspectRun(r)}
          emptyMessage="No enrichment runs yet"
        />
      </div>

      {inspectRun && (
        <Drawer
          title={`Run ${inspectRun.pack_id}@${inspectRun.pack_version} — ${inspectRun.status}`}
          onClose={() => setInspectRun(null)}
        >
          {inspectRun.error && (
            <div className="mb-3 border border-status-failed/30 bg-status-failed/10 rounded-md p-3 text-sm text-status-failed">
              {inspectRun.error}
            </div>
          )}
          <JsonViewer data={inspectRun.stats} defaultExpanded controls />
        </Drawer>
      )}
    </div>
  );
}
