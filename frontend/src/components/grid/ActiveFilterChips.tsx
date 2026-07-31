import { X } from "lucide-react";
import type { ColumnFilters } from "@/lib/columnFilters";

interface ActiveFilterChipsProps {
  filters: ColumnFilters;
  labels: Record<string, string>;
  onChange: (next: ColumnFilters) => void;
}

/** One chip per column with active filter tokens + "Clear all". */
export function ActiveFilterChips({ filters, labels, onChange }: ActiveFilterChipsProps) {
  const active = Object.entries(filters).filter(([, v]) => v.length > 0);
  if (active.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {active.map(([key, values]) => (
        <span
          key={key}
          className="flex items-center gap-1.5 text-xs px-2 py-1 rounded-md bg-accent/10 border border-accent/30 text-accent"
        >
          <span className="font-medium">{labels[key] ?? key}:</span>
          <span className="max-w-[220px] truncate">{values.join(", ")}</span>
          <button
            type="button"
            title="Clear filter"
            onClick={() => onChange({ ...filters, [key]: [] })}
            className="hover:text-text-primary transition-colors"
          >
            <X size={12} />
          </button>
        </span>
      ))}
      <button
        type="button"
        onClick={() => onChange({})}
        className="text-xs text-text-muted hover:text-text-primary transition-colors"
      >
        Clear all
      </button>
    </div>
  );
}
