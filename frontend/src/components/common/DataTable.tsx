import { cn } from "@/lib/utils";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "lucide-react";
import { LoadingSpinner } from "./LoadingSpinner";
import { EmptyState } from "./EmptyState";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  className?: string;
  /** Server-side sort key; the column header becomes clickable when set. */
  sortable?: boolean;
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
}: DataTableProps<T>) {
  if (loading) {
    return <LoadingSpinner className="py-16" />;
  }

  if (data.length === 0) {
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
                return (
                  <th
                    key={col.key}
                    onClick={sortable ? () => onSortChange(active && !descending ? `-${col.key}` : col.key) : undefined}
                    className={cn(
                      "text-left px-4 py-3 text-xs font-semibold text-text-secondary uppercase tracking-wider",
                      sortable && "cursor-pointer select-none hover:text-text-primary",
                      col.className,
                    )}
                  >
                    <span className="inline-flex items-center gap-1">
                      {col.header}
                      {active && (descending ? <ChevronDown size={12} /> : <ChevronUp size={12} />)}
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
          </tbody>
        </table>
      </div>

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
