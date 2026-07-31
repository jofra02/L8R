import { useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Filter } from "lucide-react";
import { LoadingSpinner } from "./LoadingSpinner";
import { EmptyState } from "./EmptyState";
import { ColumnFilterPopover } from "./ColumnFilterPopover";
import { distinctValues, hasActiveFilters, type ColumnFilters } from "@/lib/columnFilters";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  className?: string;
  /** Server-side sort key; the column header becomes clickable when set. */
  sortable?: boolean;
  /** Enables the funnel icon + filter popover (requires table-level filters props). */
  filterable?: boolean;
  /** Raw value used for distinct-suggestion derivation; defaults to row[key]. */
  filterAccessor?: (row: T) => unknown;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  loading?: boolean;
  page?: number;
  totalPages?: number;
  total?: number;
  onPageChange?: (page: number) => void;
  onRowClick?: (row: T) => void;
  emptyMessage?: string;
  className?: string;
  /** Current sort key, "-" prefix for descending (e.g. "-created_at"). */
  sortKey?: string;
  onSortChange?: (sort: string) => void;
  /** Controlled per-column filters (columnKey -> tokens). The table never
   * filters data itself — the parent applies filters (server params or an
   * in-memory predicate) and passes the resulting rows as `data`. */
  filters?: ColumnFilters;
  onFiltersChange?: (next: ColumnFilters) => void;
  /** Rows used to derive distinct suggestions; defaults to `data`. Client-mode
   * callers pass the unfiltered array so suggestions aren't self-limited. */
  suggestionData?: T[];
}

export function DataTable<T>({
  columns,
  data,
  loading,
  page,
  totalPages,
  total,
  onPageChange,
  onRowClick,
  emptyMessage,
  className,
  sortKey,
  onSortChange,
  filters,
  onFiltersChange,
  suggestionData,
}: DataTableProps<T>) {
  const [openFilterKey, setOpenFilterKey] = useState<string | null>(null);
  const filterButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const filteringEnabled = filters !== undefined && onFiltersChange !== undefined;
  const suggestionRows = suggestionData ?? data;

  const openColumn = filteringEnabled
    ? columns.find((c) => c.key === openFilterKey)
    : undefined;
  const suggestions = useMemo(() => {
    if (!openColumn) return [];
    const accessor = openColumn.filterAccessor ?? ((row: T) => (row as Record<string, unknown>)[openColumn.key]);
    return distinctValues(suggestionRows, accessor);
  }, [openColumn, suggestionRows]);

  if (loading) {
    return <LoadingSpinner className="py-16" />;
  }

  // With active filters, keep the header row visible on empty results —
  // otherwise the funnel to clear the filter disappears with the rows.
  const emptyWithFilters =
    data.length === 0 && filteringEnabled && hasActiveFilters(filters);
  if (data.length === 0 && !emptyWithFilters) {
    return <EmptyState message={emptyMessage} />;
  }

  return (
    <div className={cn("w-full", className)}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              {columns.map((col) => {
                const active = sortKey?.replace(/^-/, "") === col.key;
                const descending = active && sortKey?.startsWith("-");
                const sortable = col.sortable && onSortChange;
                const filterActive = (filters?.[col.key]?.length ?? 0) > 0;
                const showFunnel = filteringEnabled && col.filterable;
                return (
                  <th
                    key={col.key}
                    onClick={sortable ? () => onSortChange(active && !descending ? `-${col.key}` : col.key) : undefined}
                    className={cn(
                      "text-left px-4 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wider",
                      sortable && "cursor-pointer select-none hover:text-text-primary",
                      showFunnel && "group/th",
                      col.className,
                    )}
                  >
                    <span className="inline-flex items-center gap-1">
                      {col.header}
                      {active && (descending ? <ChevronDown size={12} /> : <ChevronUp size={12} />)}
                      {showFunnel && (
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
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {data.map((row, i) => (
              <tr
                key={i}
                onClick={() => onRowClick?.(row)}
                className={cn(
                  "border-b border-border-subtle hover:bg-elevated/50 transition-colors",
                  onRowClick && "cursor-pointer",
                )}
              >
                {columns.map((col) => (
                  <td key={col.key} className={cn("px-4 py-3 text-text-primary", col.className)}>
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
            {emptyWithFilters && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-10 text-center text-sm text-text-muted">
                  No rows match the active filters
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {openColumn && openFilterKey && filterButtonRefs.current[openFilterKey] && (
        <ColumnFilterPopover
          values={filters?.[openFilterKey] ?? []}
          onChange={(values) =>
            onFiltersChange?.({ ...filters, [openFilterKey]: values })
          }
          distinctValues={suggestions}
          onClose={() => setOpenFilterKey(null)}
          anchorEl={filterButtonRefs.current[openFilterKey]!}
        />
      )}

      {page != null && totalPages != null && onPageChange && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-border">
          <span className="text-xs text-text-muted">
            {total != null ? `${total} total` : `Page ${page} of ${totalPages}`}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onPageChange(page - 1)}
              disabled={page <= 1}
              className="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-elevated disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="text-xs text-text-secondary">
              {page} / {totalPages || 1}
            </span>
            <button
              onClick={() => onPageChange(page + 1)}
              disabled={page >= (totalPages || 1)}
              className="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-elevated disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
