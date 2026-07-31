import { useMemo, useState, type ReactNode } from "react";
import { InventoryDataGrid } from "@/components/grid/InventoryDataGrid";
import type { GridColumnSchema } from "@/components/grid/types";
import { JsonViewer } from "@/components/common/JsonViewer";
import { PropertyGrid, type PropertyGridItem } from "@/components/common/PropertyGrid";
import { EmptyState } from "@/components/common/EmptyState";
import { cn } from "@/lib/utils";
import type { AssetTypeDef } from "@/api/types";
import { columnUnion, orderedEntries, type AttrEntry } from "./classify";
import { AttributeValue } from "./AttributeValue";
import { useSyncedGridState } from "../workspace/store";
import type { ViewContext } from "../resource/types";

interface AttributeExplorerProps {
  attributes: Record<string, unknown>;
  typeDef?: AssetTypeDef;
  ctx: ViewContext;
  /** Optional per-attribute suffix (e.g. provenance chip on assets). */
  suffixFor?: (key: string) => ReactNode;
}

/** Shape-driven attributes view: General (property grid) · one filterable
 * table per object-array dataset · Raw (full JSON viewer). The same
 * component serves any resource — attributes are not normalized yet, so
 * everything derives from the runtime shape. */
export function AttributeExplorer({ attributes, typeDef, ctx, suffixFor }: AttributeExplorerProps) {
  const entries = useMemo(() => orderedEntries(attributes, typeDef), [attributes, typeDef]);
  const general = entries.filter((e) => e.kind === "scalar" || e.kind === "chips");
  const flatObjects = entries.filter((e) => e.kind === "flatObject");
  const datasets = entries.filter((e) => e.kind === "objectArray");

  const tabs = [
    { id: "general", label: "General", count: undefined as number | undefined },
    ...datasets.map((d) => ({
      id: `ds:${d.key}`,
      label: d.label,
      count: (d.value as unknown[]).length,
    })),
    { id: "raw", label: "Raw", count: undefined },
  ];

  const [selected, setSelected] = useState("general");
  const activeId = tabs.some((t) => t.id === selected) ? selected : "general";

  if (entries.length === 0) {
    return <EmptyState title="No attributes" message="This resource has no recorded attributes" />;
  }

  return (
    <div className="space-y-3">
      <div className="border-b border-border-subtle flex gap-0 overflow-x-auto">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setSelected(t.id)}
            className={cn(
              "px-3 py-2 text-xs font-medium transition-colors border-b-2 -mb-px whitespace-nowrap inline-flex items-center gap-1.5",
              activeId === t.id
                ? "border-accent text-text-primary"
                : "border-transparent text-text-muted hover:text-text-secondary",
            )}
          >
            {t.label}
            {t.count !== undefined && (
              <span className="px-1.5 rounded-full bg-elevated border border-border text-[10px] text-text-secondary">
                {t.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {activeId === "general" && (
        <div className="space-y-4">
          <div className="bg-card border border-border rounded-lg px-5 py-2">
            <PropertyGrid
              columns={2}
              items={general.map<PropertyGridItem>((e) => ({
                label: e.label,
                value:
                  e.kind === "chips" ? (
                    <ChipList values={e.value as unknown[]} />
                  ) : (
                    <AttributeValue value={e.value} fieldType={e.fieldDef?.type} />
                  ),
                suffix: suffixFor?.(e.key),
              }))}
            />
            {general.length === 0 && flatObjects.length === 0 && (
              <p className="text-sm text-text-muted py-3">No scalar attributes</p>
            )}
          </div>
          {flatObjects.map((e) => (
            <div key={e.key} className="bg-card border border-border rounded-lg px-5 py-2">
              <div className="flex items-center justify-between pt-2">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
                  {e.label}
                </h4>
                {suffixFor?.(e.key)}
              </div>
              <PropertyGrid
                columns={2}
                items={Object.entries(e.value as Record<string, unknown>).map(([k, v]) => ({
                  label: k,
                  value: <AttributeValue value={v} />,
                }))}
              />
            </div>
          ))}
        </div>
      )}

      {datasets.map(
        (entry) =>
          activeId === `ds:${entry.key}` && (
            <DatasetGrid key={entry.key} entry={entry} ctx={ctx} suffix={suffixFor?.(entry.key)} />
          ),
      )}

      {activeId === "raw" && (
        <div className="bg-card border border-border rounded-lg p-4">
          <JsonViewer data={attributes} defaultExpanded controls />
        </div>
      )}
    </div>
  );
}

function ChipList({ values }: { values: unknown[] }) {
  if (values.length === 0) return <span className="text-text-muted">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {values.map((v, i) => (
        <span
          key={i}
          className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary"
        >
          {String(v)}
        </span>
      ))}
    </span>
  );
}

interface IndexedRow {
  id: string;
  row: Record<string, unknown>;
}

function DatasetGrid({ entry, ctx, suffix }: { entry: AttrEntry; ctx: ViewContext; suffix?: ReactNode }) {
  const rows = entry.value as Record<string, unknown>[];
  const indexed = useMemo<IndexedRow[]>(
    () => rows.map((row, i) => ({ id: String(i), row })),
    [rows],
  );
  // Store-backed (never URL: several grids share the view) — state still
  // survives tab switches and back navigation.
  const [state, setState] = useSyncedGridState(`${ctx.stateKeyPrefix}|attr|${entry.key}`, false, {
    pageSize: 50,
  });
  const columns = useMemo<GridColumnSchema<IndexedRow>[]>(
    () =>
      columnUnion(rows).map((key) => ({
        key,
        header: key,
        type: "complex",
        sortable: true,
        filterable: true,
        accessor: (r) => r.row[key],
      })),
    [rows],
  );
  return (
    <div className="bg-card border border-border rounded-lg">
      {suffix && <div className="px-3 pt-2 flex justify-end">{suffix}</div>}
      <InventoryDataGrid<IndexedRow>
        gridId={`attr.${entry.key}`}
        columns={columns}
        data={indexed}
        mode="client"
        state={state}
        onStateChange={setState}
        getRowId={(r) => r.id}
        emptyMessage="No rows"
      />
    </div>
  );
}
