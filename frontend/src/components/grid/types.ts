import type { ReactNode } from "react";
import type { ColumnFilters } from "@/lib/columnFilters";

/** Field types resolved by the cell renderer registry (cellRenderers.tsx).
 * Unknown/omitted types fall back to "text". */
export type GridFieldType =
  | "text"
  | "code"
  | "number"
  | "date"
  | "timeago"
  | "badge"
  | "boolean"
  | "link"
  | "complex";

/** Column described by metadata, not by markup — resource adapters and
 * type schemas build these; the grid renders them via the registry. */
export interface GridColumnSchema<T = unknown> {
  key: string;
  header: string;
  type?: GridFieldType;
  /** Raw value for rendering, filtering, sorting and export; defaults to row[key]. */
  accessor?: (row: T) => unknown;
  /** Full custom cell — overrides the registry renderer. */
  render?: (row: T) => ReactNode;
  sortable?: boolean;
  filterable?: boolean;
  /** Initial width in px (user resize overrides, persisted per gridId). */
  width?: number;
  minWidth?: number;
  /** Primary identifier column: clicking the cell opens the resource. */
  primary?: boolean;
  /** Start hidden; the user can enable it from the Columns menu. */
  defaultHidden?: boolean;
}

/** Controlled grid state. The grid never fetches or filters by itself in
 * server mode — the parent maps this to query params. In client mode the
 * grid applies the same filter/sort semantics in memory. */
export interface GridState {
  filters: ColumnFilters;
  /** "-" prefix = descending (matches the backend sort convention). */
  sort?: string;
  page: number;
  pageSize: number;
}

export const DEFAULT_GRID_STATE: GridState = { filters: {}, page: 1, pageSize: 25 };

/** Layout persisted per gridId in localStorage (invgrid:<gridId>). */
export interface GridPersistedLayout {
  sizing?: Record<string, number>;
  order?: string[];
  hidden?: string[];
}

export interface ContextMenuItem {
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  danger?: boolean;
}
