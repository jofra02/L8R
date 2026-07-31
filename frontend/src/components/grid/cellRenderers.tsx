import type { ReactNode } from "react";
import { format } from "date-fns";
import { Maximize2 } from "lucide-react";
import { TimeAgo } from "@/components/common/TimeAgo";
import type { GridFieldType } from "./types";

/** Readable one-line summary for objects/arrays shown inside a cell.
 * Full values open in the inspector drawer — never raw JSON in cells. */
export function summarizeValue(value: unknown): string {
  if (Array.isArray(value)) {
    return `${value.length} item${value.length === 1 ? "" : "s"}`;
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    const scalars = entries.filter(([, v]) => v === null || typeof v !== "object");
    const preview = scalars
      .slice(0, 2)
      .map(([k, v]) => `${k}: ${String(v)}`)
      .join(", ");
    return preview || `${entries.length} field${entries.length === 1 ? "" : "s"}`;
  }
  return String(value ?? "");
}

export interface CellContext {
  columnHeader: string;
  /** Open a full value in the grid's inspector drawer. */
  openValue: (title: string, value: unknown) => void;
}

const dash = <span className="text-text-muted">—</span>;

type Renderer = (value: unknown, ctx: CellContext) => ReactNode;

function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

const text: Renderer = (value) =>
  isEmpty(value) ? dash : <span className="text-text-secondary">{String(value)}</span>;

const RENDERERS: Record<GridFieldType, Renderer> = {
  text,
  link: (value) =>
    isEmpty(value) ? dash : (
      <span className="text-text-primary font-medium hover:text-accent hover:underline">
        {String(value)}
      </span>
    ),
  code: (value) =>
    isEmpty(value) ? dash : (
      <span className="font-mono text-xs text-text-secondary">{String(value)}</span>
    ),
  number: (value) =>
    isEmpty(value) ? dash : (
      <span className="tabular-nums text-text-secondary">
        {typeof value === "number" ? value.toLocaleString() : String(value)}
      </span>
    ),
  date: (value) => {
    if (isEmpty(value)) return dash;
    const d = new Date(String(value));
    return (
      <span className="text-text-secondary">
        {isNaN(d.getTime()) ? String(value) : format(d, "yyyy-MM-dd")}
      </span>
    );
  },
  timeago: (value) => (isEmpty(value) ? dash : <TimeAgo date={String(value)} />),
  badge: (value) =>
    isEmpty(value) ? dash : (
      <span className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary whitespace-nowrap">
        {String(value)}
      </span>
    ),
  boolean: (value) =>
    isEmpty(value) ? dash : (
      <span className="text-text-secondary">{value ? "Yes" : "No"}</span>
    ),
  complex: (value, ctx) => {
    if (isEmpty(value)) return dash;
    if (typeof value !== "object") return text(value, ctx);
    return (
      <button
        type="button"
        title="Inspect value"
        onClick={(e) => {
          e.stopPropagation();
          ctx.openValue(ctx.columnHeader, value);
        }}
        className="inline-flex items-center gap-1.5 text-xs text-text-secondary hover:text-accent transition-colors"
      >
        <span className="truncate max-w-[240px]">{summarizeValue(value)}</span>
        <Maximize2 size={11} className="shrink-0" />
      </button>
    );
  },
};

export function renderCell(
  type: GridFieldType | undefined,
  value: unknown,
  ctx: CellContext,
): ReactNode {
  return (RENDERERS[type ?? "text"] ?? RENDERERS.text)(value, ctx);
}
