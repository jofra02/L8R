import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface PropertyGridItem {
  label: string;
  value: ReactNode;
  /** Trailing slot (e.g. a provenance chip). */
  suffix?: ReactNode;
}

interface PropertyGridProps {
  items: PropertyGridItem[];
  /** Max columns on wide screens (1–3); default 3. */
  columns?: 1 | 2 | 3;
  className?: string;
}

/** Dense key/value property table (PROPERTY | VALUE), 2–3 columns of pairs
 * on desktop. Replaces the old free-form card grids. */
export function PropertyGrid({ items, columns = 3, className }: PropertyGridProps) {
  const cols =
    columns === 1
      ? "grid-cols-1"
      : columns === 2
        ? "grid-cols-1 lg:grid-cols-2"
        : "grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3";
  return (
    <div className={cn("grid gap-x-10", cols, className)}>
      {items.map((item, i) => (
        <div
          key={`${item.label}-${i}`}
          className="grid grid-cols-[minmax(120px,190px)_1fr] items-baseline gap-3 py-1.5 border-b border-border-subtle min-w-0"
        >
          <span className="text-xs text-text-secondary truncate" title={item.label}>
            {item.label}
          </span>
          <span className="text-sm text-text-primary min-w-0 break-words flex items-baseline justify-between gap-2">
            <span className="min-w-0">{item.value ?? <span className="text-text-muted">—</span>}</span>
            {item.suffix}
          </span>
        </div>
      ))}
    </div>
  );
}
