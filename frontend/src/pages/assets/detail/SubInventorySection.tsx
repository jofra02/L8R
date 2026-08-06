import { useMemo, useRef } from "react";
import { Copy, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { InventoryDataGrid } from "@/components/grid/InventoryDataGrid";
import type { GridColumnSchema } from "@/components/grid/types";
import { cn } from "@/lib/utils";
import { serializeFilters } from "@/lib/columnFilters";
import { useAssetSubitemChildren } from "@/hooks/useAssets";
import type { AssetSubitem } from "@/api/types";
import { columnUnion } from "../attributes/classify";
import { useSyncedGridState } from "../workspace/store";
import { useWorkspace } from "../workspace/WorkspaceContext";
import type { ViewContext } from "../resource/types";

/** Column filters the subitems API can evaluate server-side. */
const SERVER_FILTER_KEYS = ["name", "kind", "state", "external_id", "source"];

interface SubInventorySectionProps {
  assetId: string;
  /** "root" = direct children of the asset; otherwise a subitem id. */
  parentSubitemId: string;
  ctx: ViewContext;
}

/** Generic children collection: the SAME view at every hierarchy level —
 * direct children only, drill-down repeats the resource shell. Filtering
 * uses the standard per-column model (no custom search inputs). */
export function SubInventorySection({ assetId, parentSubitemId, ctx }: SubInventorySectionProps) {
  const { navigateTo, openSubitemInNewTab } = useWorkspace();
  const [gridState, setGridState] = useSyncedGridState(
    `${ctx.stateKeyPrefix}|sub-inventory`,
    ctx.active,
    { sort: "name" },
  );

  const presence = gridState.filters["presence"] ?? [];
  const absentOnly = presence.length === 1 && presence[0] === "absent";
  const absentParam =
    presence.length === 1
      ? presence[0] === "absent"
        ? true
        : presence[0] === "present"
          ? false
          : undefined
      : undefined;

  const serverFilters = Object.fromEntries(
    Object.entries(gridState.filters).filter(([k]) => SERVER_FILTER_KEYS.includes(k)),
  );

  const { data, isLoading, error, refetch } = useAssetSubitemChildren(assetId, parentSubitemId, {
    page: gridState.page,
    page_size: gridState.pageSize,
    sort: gridState.sort,
    ...(absentParam !== undefined && { absent: absentParam }),
    ...serializeFilters(serverFilters),
  });
  const rows = useMemo(() => data?.items ?? [], [data]);

  // Discovered attribute columns: union of keys seen so far, append-only so
  // columns don't shift while paging through server results.
  const discoveredRef = useRef<string[]>([]);
  const discovered = useMemo(() => {
    for (const key of columnUnion(rows.map((r) => r.attributes))) {
      if (!discoveredRef.current.includes(key)) discoveredRef.current.push(key);
    }
    return [...discoveredRef.current];
  }, [rows]);

  const columns = useMemo<GridColumnSchema<AssetSubitem>[]>(
    () => [
      { key: "name", header: "Name", type: "link", sortable: true, filterable: true, primary: true, width: 220 },
      { key: "kind", header: "Kind", type: "badge", sortable: true, filterable: true, width: 110 },
      { key: "state", header: "State", type: "badge", sortable: true, filterable: true, width: 110 },
      { key: "external_id", header: "External ID", type: "code", sortable: true, filterable: true, width: 150 },
      { key: "source", header: "Source", type: "badge", sortable: true, filterable: true, width: 110 },
      {
        key: "presence",
        header: "Presence",
        filterable: true,
        width: 100,
        accessor: (r) => (r.absent ? "absent" : "present"),
        render: (r) => (
          <span
            className={cn(
              "text-xs px-2 py-0.5 rounded border",
              r.absent
                ? "bg-severity-critical/10 border-severity-critical/30 text-severity-critical"
                : "bg-severity-low/10 border-severity-low/30 text-severity-low",
            )}
          >
            {r.absent ? "absent" : "present"}
          </span>
        ),
      },
      {
        key: "children_count",
        header: "Children",
        type: "number",
        width: 90,
        accessor: (r) => (r.children_count > 0 ? r.children_count : null),
      },
      { key: "last_seen_at", header: "Last seen", type: "timeago", sortable: true, width: 120 },
      ...discovered.map<GridColumnSchema<AssetSubitem>>((key, i) => ({
        key: `attr:${key}`,
        header: key,
        type: "complex",
        accessor: (r) => r.attributes[key],
        defaultHidden: i >= 2,
      })),
    ],
    [discovered],
  );

  const open = (row: AssetSubitem) => navigateTo(`${assetId}/sub/${row.id}`, { push: true });

  return (
    <div className="bg-card border border-border rounded-lg">
      <InventoryDataGrid<AssetSubitem>
        gridId="subitems.children"
        columns={columns}
        data={rows}
        mode="server"
        state={gridState}
        onStateChange={setGridState}
        total={data?.total}
        loading={isLoading}
        error={error ?? undefined}
        onRetry={() => refetch()}
        getRowId={(r) => r.id}
        onOpen={open}
        emptyMessage="No discovered inventory"
        contextMenuItems={(r) => [
          { label: "Open", icon: <ExternalLink size={13} />, onSelect: () => open(r) },
          {
            label: "Open in new tab",
            icon: <ExternalLink size={13} />,
            onSelect: () => openSubitemInNewTab(assetId, r.id),
          },
          {
            label: "Copy ID",
            icon: <Copy size={13} />,
            onSelect: () => {
              navigator.clipboard.writeText(r.id).then(
                () => toast.success("Subitem ID copied"),
                () => toast.error("Copy failed"),
              );
            },
          },
        ]}
        quickFilters={
          <button
            type="button"
            onClick={() =>
              setGridState({
                ...gridState,
                filters: { ...gridState.filters, presence: absentOnly ? [] : ["absent"] },
                page: 1,
              })
            }
            className={cn(
              "text-xs px-2.5 py-1 rounded-md border transition-colors",
              absentOnly
                ? "bg-accent/10 border-accent/40 text-accent"
                : "bg-elevated border-border text-text-secondary hover:text-text-primary",
            )}
          >
            Absent only
          </button>
        }
      />
    </div>
  );
}
