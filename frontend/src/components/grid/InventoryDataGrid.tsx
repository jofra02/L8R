import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type ColumnOrderState,
  type ColumnSizingState,
  type VisibilityState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  AlertTriangle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Columns3,
  Download,
  Filter,
} from "lucide-react";
import { cn, downloadBlob } from "@/lib/utils";
import { ColumnFilterPopover } from "@/components/common/ColumnFilterPopover";
import { ContextMenu } from "@/components/common/ContextMenu";
import { Drawer } from "@/components/common/Drawer";
import { JsonViewer } from "@/components/common/JsonViewer";
import {
  distinctValues,
  hasActiveFilters,
  matchesFilters,
  sortRowsClientSide,
  type ColumnFilters,
} from "@/lib/columnFilters";
import { renderCell, type CellContext } from "./cellRenderers";
import { ActiveFilterChips } from "./ActiveFilterChips";
import { GridSkeletonRows } from "./GridSkeleton";
import type { ContextMenuItem, GridColumnSchema, GridState } from "./types";

interface InventoryDataGridProps<T> {
  /** Layout persistence key (localStorage invgrid:<gridId>) — one per
   * resource-type/view, NOT per resource instance. */
  gridId: string;
  columns: GridColumnSchema<T>[];
  /** Server mode: the current page as returned by the API (already filtered
   * and sorted). Client mode: the full row set; the grid filters/sorts/pages
   * in memory with the same token semantics. */
  data: T[];
  mode: "server" | "client";
  state: GridState;
  onStateChange: (next: GridState) => void;
  /** Server mode only: total row count across pages. */
  total?: number;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  getRowId: (row: T) => string;
  selectedRowId?: string | null;
  onSelect?: (row: T | null) => void;
  /** Open the resource: primary-cell click, double click, Enter. */
  onOpen?: (row: T) => void;
  contextMenuItems?: (row: T) => ContextMenuItem[];
  emptyMessage?: string;
  /** Extra toolbar controls (quick filters), rendered left of the chips. */
  quickFilters?: ReactNode;
  /** Enables client-side CSV export of the loaded rows. */
  exportFileName?: string;
  /** Client mode: switch from pagination to virtualization above this row
   * count. Default 100. */
  virtualizeAt?: number;
  /** Labels for the active-filter chips; defaults to column headers. */
  className?: string;
}

interface PersistedLayout {
  sizing?: Record<string, number>;
  order?: string[];
  hidden?: string[];
}

function loadLayout(gridId: string): PersistedLayout {
  try {
    return JSON.parse(localStorage.getItem(`invgrid:${gridId}`) ?? "{}") as PersistedLayout;
  } catch {
    return {};
  }
}

function cellText(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function csvEscape(text: string): string {
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

const ROW_HEIGHT = 41;

export function InventoryDataGrid<T>({
  gridId,
  columns: schema,
  data,
  mode,
  state,
  onStateChange,
  total,
  loading,
  error,
  onRetry,
  getRowId,
  selectedRowId,
  onSelect,
  onOpen,
  contextMenuItems,
  emptyMessage = "No data",
  quickFilters,
  exportFileName,
  virtualizeAt = 100,
  className,
}: InventoryDataGridProps<T>) {
  const accessorByKey = useMemo(() => {
    const map: Record<string, (row: T) => unknown> = {};
    for (const col of schema) {
      map[col.key] = col.accessor ?? ((row: T) => (row as Record<string, unknown>)[col.key]);
    }
    return map;
  }, [schema]);
  const accessorOf = (key: string) => accessorByKey[key] ?? (() => undefined);

  // --- data pipeline (client mode mirrors the server filter semantics) ---
  const processed = useMemo(() => {
    if (mode === "server") return data;
    const filtered = data.filter((row) =>
      matchesFilters(row, state.filters, (r, key) => accessorOf(key)(r)),
    );
    return sortRowsClientSide(filtered, state.sort, (r, key) => accessorOf(key)(r));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, data, state.filters, state.sort, accessorByKey]);

  const virtualized = mode === "client" && processed.length > virtualizeAt;
  const pageRows = useMemo(() => {
    if (mode === "server" || virtualized) return processed;
    const start = (state.page - 1) * state.pageSize;
    return processed.slice(start, start + state.pageSize);
  }, [mode, virtualized, processed, state.page, state.pageSize]);

  const effectiveTotal = mode === "server" ? (total ?? data.length) : processed.length;
  const totalPages = virtualized ? 1 : Math.max(1, Math.ceil(effectiveTotal / state.pageSize));

  // --- layout persistence ---
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>(
    () => loadLayout(gridId).sizing ?? {},
  );
  const [columnOrder, setColumnOrder] = useState<ColumnOrderState>(() => {
    const saved = loadLayout(gridId).order ?? [];
    const keys = schema.map((c) => c.key);
    return [...saved.filter((k) => keys.includes(k)), ...keys.filter((k) => !saved.includes(k))];
  });
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(() => {
    const savedHidden = loadLayout(gridId).hidden;
    const hidden = savedHidden ?? schema.filter((c) => c.defaultHidden).map((c) => c.key);
    return Object.fromEntries(hidden.map((k) => [k, false]));
  });

  useEffect(() => {
    const hidden = Object.entries(columnVisibility)
      .filter(([, v]) => v === false)
      .map(([k]) => k);
    const layout: PersistedLayout = { sizing: columnSizing, order: columnOrder, hidden };
    try {
      localStorage.setItem(`invgrid:${gridId}`, JSON.stringify(layout));
    } catch {
      /* storage full/unavailable — layout just won't persist */
    }
  }, [gridId, columnSizing, columnOrder, columnVisibility]);

  // Schema can grow (discovered columns): register new keys in the order.
  useEffect(() => {
    setColumnOrder((order) => {
      const missing = schema.map((c) => c.key).filter((k) => !order.includes(k));
      return missing.length ? [...order, ...missing] : order;
    });
  }, [schema]);

  // --- inspector drawer for complex values ---
  const [inspect, setInspect] = useState<{ title: string; value: unknown } | null>(null);

  const columnDefs = useMemo<ColumnDef<T>[]>(
    () =>
      schema.map((col) => ({
        id: col.key,
        accessorFn: col.accessor ?? ((row: T) => (row as Record<string, unknown>)[col.key]),
        size: col.width ?? 150,
        minSize: col.minWidth ?? 60,
      })),
    [schema],
  );

  const table = useReactTable({
    data: pageRows,
    columns: columnDefs,
    state: { columnSizing, columnOrder, columnVisibility },
    onColumnSizingChange: setColumnSizing,
    onColumnOrderChange: setColumnOrder,
    onColumnVisibilityChange: setColumnVisibility,
    columnResizeMode: "onChange",
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => getRowId(row),
  });
  const schemaByKey = useMemo(
    () => Object.fromEntries(schema.map((c) => [c.key, c])) as Record<string, GridColumnSchema<T>>,
    [schema],
  );
  const visibleLeafColumns = table.getVisibleLeafColumns();

  // --- virtualization ---
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: virtualized ? pageRows.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });
  const virtualItems = virtualized ? virtualizer.getVirtualItems() : [];
  const padTop = virtualized && virtualItems.length > 0 ? (virtualItems[0]?.start ?? 0) : 0;
  const padBottom =
    virtualized && virtualItems.length > 0
      ? virtualizer.getTotalSize() - (virtualItems[virtualItems.length - 1]?.end ?? 0)
      : 0;
  const renderRows = virtualized
    ? virtualItems.map((v) => pageRows[v.index]).filter((r): r is T => r !== undefined)
    : pageRows;

  // --- filters popover ---
  const [openFilterKey, setOpenFilterKey] = useState<string | null>(null);
  const filterButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const openColumn = openFilterKey ? schemaByKey[openFilterKey] : undefined;
  const suggestions = useMemo(() => {
    if (!openColumn) return [];
    return distinctValues(mode === "client" ? data : pageRows, (row: T) =>
      accessorOf(openColumn.key)(row),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openColumn, mode, data, pageRows]);

  const setFilters = (filters: ColumnFilters) => onStateChange({ ...state, filters, page: 1 });
  const setSort = (sort: string) => onStateChange({ ...state, sort, page: 1 });
  const setPage = (page: number) => onStateChange({ ...state, page });

  // --- context menu / selection / keyboard ---
  const [menu, setMenu] = useState<{ x: number; y: number; row: T } | null>(null);

  const selectedIndex = selectedRowId
    ? pageRows.findIndex((r) => getRowId(r) === selectedRowId)
    : -1;

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next =
        e.key === "ArrowDown"
          ? pageRows[Math.min(selectedIndex + 1, pageRows.length - 1)]
          : pageRows[Math.max(selectedIndex - 1, 0)];
      if (next !== undefined) onSelect?.(next);
    } else if (e.key === "Enter" && selectedIndex >= 0) {
      const row = pageRows[selectedIndex];
      if (row !== undefined) onOpen?.(row);
    } else if (e.key === "Escape") {
      onSelect?.(null);
    }
  };

  // --- columns menu ---
  const [columnsMenuOpen, setColumnsMenuOpen] = useState(false);
  const columnsMenuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!columnsMenuOpen) return;
    const onMouseDown = (e: MouseEvent) => {
      if (!columnsMenuRef.current?.contains(e.target as Node)) setColumnsMenuOpen(false);
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [columnsMenuOpen]);

  const dragKey = useRef<string | null>(null);

  const filterLabels = useMemo(
    () => Object.fromEntries(schema.map((c) => [c.key, c.header])),
    [schema],
  );

  const exportCsv = () => {
    const cols = visibleLeafColumns
      .map((c) => schemaByKey[c.id])
      .filter((c): c is GridColumnSchema<T> => c !== undefined);
    const lines = [cols.map((c) => csvEscape(c.header)).join(",")];
    for (const row of processed) {
      lines.push(cols.map((c) => csvEscape(cellText(accessorOf(c.key)(row)))).join(","));
    }
    downloadBlob(new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" }), `${exportFileName}.csv`);
  };

  const colSpan = Math.max(1, visibleLeafColumns.length);
  const showEmpty = !loading && !error && pageRows.length === 0;

  return (
    <div className={cn("w-full", className)}>
      {/* Toolbar: quick filters + active chips left, column controls right */}
      <div className="flex items-center gap-3 px-3 py-2 border-b border-border-subtle">
        <div className="flex items-center gap-3 flex-wrap flex-1 min-w-0">
          {quickFilters}
          <ActiveFilterChips filters={state.filters} labels={filterLabels} onChange={setFilters} />
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {exportFileName && (
            <button
              type="button"
              title="Export visible rows (CSV)"
              onClick={exportCsv}
              className="p-1.5 rounded text-text-secondary hover:text-text-primary hover:bg-elevated transition-colors"
            >
              <Download size={14} />
            </button>
          )}
          <div ref={columnsMenuRef} className="relative">
            <button
              type="button"
              title="Columns"
              onClick={() => setColumnsMenuOpen((v) => !v)}
              className={cn(
                "p-1.5 rounded transition-colors",
                columnsMenuOpen
                  ? "text-text-primary bg-elevated"
                  : "text-text-secondary hover:text-text-primary hover:bg-elevated",
              )}
            >
              <Columns3 size={14} />
            </button>
            {columnsMenuOpen && (
              <div className="absolute right-0 top-full mt-1 z-30 w-52 max-h-72 overflow-y-auto py-1 bg-elevated border border-border rounded-md shadow-xl">
                {columnOrder
                  .map((key) => schemaByKey[key])
                  .filter((c): c is GridColumnSchema<T> => c !== undefined)
                  .map((col) => {
                    const visible = columnVisibility[col.key] !== false;
                    return (
                      <label
                        key={col.key}
                        className="flex items-center gap-2 px-3 py-1.5 text-sm text-text-secondary hover:bg-card hover:text-text-primary cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={visible}
                          onChange={() =>
                            setColumnVisibility((v) => ({ ...v, [col.key]: !visible }))
                          }
                          className="accent-[#2f81f7]"
                        />
                        <span className="truncate">{col.header}</span>
                      </label>
                    );
                  })}
              </div>
            )}
          </div>
        </div>
      </div>

      <div
        ref={scrollRef}
        tabIndex={0}
        onKeyDown={onKeyDown}
        className={cn(
          "overflow-auto focus:outline-none",
          virtualized ? "max-h-[65vh]" : "max-h-[72vh]",
        )}
      >
        <table
          className="text-sm border-separate border-spacing-0"
          style={{ width: table.getTotalSize(), minWidth: "100%" }}
        >
          <thead className="sticky top-0 z-10">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((header) => {
                  const col = schemaByKey[header.column.id];
                  if (!col) return null;
                  const active = state.sort?.replace(/^-/, "") === col.key;
                  const descending = active && state.sort?.startsWith("-");
                  const filterActive = (state.filters[col.key]?.length ?? 0) > 0;
                  return (
                    <th
                      key={header.id}
                      style={{ width: header.getSize() }}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        e.preventDefault();
                        const from = dragKey.current;
                        dragKey.current = null;
                        if (!from || from === col.key) return;
                        setColumnOrder((order) => {
                          const next = order.filter((k) => k !== from);
                          next.splice(next.indexOf(col.key), 0, from);
                          return next;
                        });
                      }}
                      className={cn(
                        "relative text-left px-3 py-2 text-xs font-semibold text-text-secondary uppercase tracking-wider",
                        "bg-card border-b border-border select-none group/th",
                        col.sortable && "cursor-pointer hover:text-text-primary",
                      )}
                      onClick={
                        col.sortable
                          ? () => setSort(active && !descending ? `-${col.key}` : col.key)
                          : undefined
                      }
                    >
                      <span className="inline-flex items-center gap-1 max-w-full">
                        <span
                          draggable
                          onDragStart={(e) => {
                            dragKey.current = col.key;
                            e.dataTransfer.effectAllowed = "move";
                          }}
                          className="truncate cursor-grab active:cursor-grabbing"
                          title={col.header}
                        >
                          {col.header}
                        </span>
                        {active &&
                          (descending ? <ChevronDown size={12} /> : <ChevronUp size={12} />)}
                        {col.filterable && (
                          <button
                            ref={(el) => {
                              filterButtonRefs.current[col.key] = el;
                            }}
                            type="button"
                            title="Filter"
                            onClick={(e) => {
                              e.stopPropagation();
                              setOpenFilterKey(openFilterKey === col.key ? null : col.key);
                            }}
                            className={cn(
                              "p-0.5 rounded transition-colors",
                              filterActive
                                ? "text-accent"
                                : "text-text-muted opacity-0 group-hover/th:opacity-100 hover:text-text-primary",
                              openFilterKey === col.key && "opacity-100 text-text-primary",
                            )}
                          >
                            <Filter size={12} fill={filterActive ? "currentColor" : "none"} />
                          </button>
                        )}
                      </span>
                      <div
                        onMouseDown={header.getResizeHandler()}
                        onTouchStart={header.getResizeHandler()}
                        onClick={(e) => e.stopPropagation()}
                        className={cn(
                          "absolute right-0 top-0 h-full w-1.5 cursor-col-resize touch-none",
                          "hover:bg-accent/60",
                          header.column.getIsResizing() && "bg-accent",
                        )}
                      />
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {loading && pageRows.length === 0 ? (
              <GridSkeletonRows columns={colSpan} />
            ) : error ? (
              <tr>
                <td colSpan={colSpan} className="px-4 py-10 text-center">
                  <div className="inline-flex flex-col items-center gap-2 text-sm text-text-secondary">
                    <AlertTriangle size={18} className="text-severity-high" />
                    <span>Failed to load data</span>
                    {onRetry && (
                      <button
                        type="button"
                        onClick={onRetry}
                        className="text-xs text-accent hover:text-accent-hover transition-colors"
                      >
                        Retry
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ) : showEmpty ? (
              <tr>
                <td colSpan={colSpan} className="px-4 py-10 text-center text-sm text-text-muted">
                  {hasActiveFilters(state.filters)
                    ? "No rows match the active filters"
                    : emptyMessage}
                </td>
              </tr>
            ) : (
              <>
                {padTop > 0 && (
                  <tr aria-hidden>
                    <td colSpan={colSpan} style={{ height: padTop, padding: 0, border: 0 }} />
                  </tr>
                )}
                {renderRows.map((row) => {
                  const id = getRowId(row);
                  const selected = selectedRowId === id;
                  return (
                    <tr
                      key={id}
                      onClick={() => onSelect?.(row)}
                      onDoubleClick={() => onOpen?.(row)}
                      onContextMenu={
                        contextMenuItems
                          ? (e) => {
                              e.preventDefault();
                              onSelect?.(row);
                              setMenu({ x: e.clientX, y: e.clientY, row });
                            }
                          : undefined
                      }
                      className={cn(
                        "transition-colors",
                        selected ? "bg-accent/10" : "hover:bg-elevated/50",
                        (onSelect || onOpen) && "cursor-pointer",
                      )}
                      style={{ height: ROW_HEIGHT }}
                    >
                      {table
                        .getRow(id)
                        .getVisibleCells()
                        .map((cell) => {
                          const col = schemaByKey[cell.column.id];
                          if (!col) return null;
                          const ctx: CellContext = {
                            columnHeader: col.header,
                            openValue: (title, value) => setInspect({ title, value }),
                          };
                          const content = col.render
                            ? col.render(row)
                            : renderCell(col.type, cell.getValue(), ctx);
                          return (
                            <td
                              key={cell.id}
                              style={{ width: cell.column.getSize() }}
                              onClick={
                                col.primary && onOpen
                                  ? (e) => {
                                      e.stopPropagation();
                                      onOpen(row);
                                    }
                                  : undefined
                              }
                              className={cn(
                                "px-3 py-2 border-b border-border-subtle text-text-primary overflow-hidden whitespace-nowrap text-ellipsis",
                                col.primary && onOpen && "cursor-pointer",
                              )}
                            >
                              {content}
                            </td>
                          );
                        })}
                    </tr>
                  );
                })}
                {padBottom > 0 && (
                  <tr aria-hidden>
                    <td colSpan={colSpan} style={{ height: padBottom, padding: 0, border: 0 }} />
                  </tr>
                )}
              </>
            )}
          </tbody>
        </table>
      </div>

      {/* Footer: row count + pagination */}
      <div className="flex items-center justify-between px-3 py-2 border-t border-border">
        <span className="text-xs text-text-muted">
          {mode === "client" && hasActiveFilters(state.filters)
            ? `${processed.length} / ${data.length} rows`
            : `${effectiveTotal} row${effectiveTotal === 1 ? "" : "s"}`}
        </span>
        {!virtualized && totalPages > 1 && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage(state.page - 1)}
              disabled={state.page <= 1}
              className="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-elevated disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="text-xs text-text-secondary">
              {state.page} / {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage(state.page + 1)}
              disabled={state.page >= totalPages}
              className="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-elevated disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        )}
      </div>

      {openColumn && openFilterKey && filterButtonRefs.current[openFilterKey] && (
        <ColumnFilterPopover
          values={state.filters[openFilterKey] ?? []}
          onChange={(values) => setFilters({ ...state.filters, [openFilterKey]: values })}
          distinctValues={suggestions}
          onClose={() => setOpenFilterKey(null)}
          anchorEl={filterButtonRefs.current[openFilterKey]!}
        />
      )}

      {menu && contextMenuItems && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          items={contextMenuItems(menu.row)}
          onClose={() => setMenu(null)}
        />
      )}

      {inspect && (
        <Drawer title={inspect.title} onClose={() => setInspect(null)}>
          <JsonViewer data={inspect.value} defaultExpanded controls />
        </Drawer>
      )}
    </div>
  );
}
