/** Column filter model shared by server-driven and client-driven tables.
 *
 * Semantics: within a column, tokens are OR (any case-insensitive substring
 * match); across columns, AND. The server mirrors these semantics
 * (exact IN for enum-like columns, OR-of-ILIKE for free text).
 */

/** columnKey -> entered filter tokens */
export type ColumnFilters = Record<string, string[]>;

export function parseFilterInput(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

export function hasActiveFilters(filters: ColumnFilters): boolean {
  return Object.values(filters).some((v) => v.length > 0);
}

/** Comma-join for server query params: {"name": ["a","b"]} -> {"name": "a,b"}.
 * Values stay flat strings so react-query keys hash stably. */
export function serializeFilters(filters: ColumnFilters): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, values] of Object.entries(filters)) {
    if (values.length > 0) out[key] = values.join(",");
  }
  return out;
}

function valueText(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Client-side predicate mirroring the server semantics. */
export function matchesFilters<T>(
  row: T,
  filters: ColumnFilters,
  accessor: (row: T, key: string) => unknown,
): boolean {
  for (const [key, tokens] of Object.entries(filters)) {
    if (tokens.length === 0) continue;
    const text = valueText(accessor(row, key)).toLowerCase();
    if (!tokens.some((t) => text.includes(t.toLowerCase()))) return false;
  }
  return true;
}

/** Client-side sort: "-" prefix = descending; numbers compare numerically,
 * everything else falls back to case-insensitive string compare. */
export function sortRowsClientSide<T>(
  rows: T[],
  sortKey: string | undefined,
  accessor: (row: T, key: string) => unknown,
): T[] {
  if (!sortKey) return rows;
  const desc = sortKey.startsWith("-");
  const key = desc ? sortKey.slice(1) : sortKey;
  const sorted = [...rows].sort((a, b) => {
    const va = accessor(a, key);
    const vb = accessor(b, key);
    if (va == null && vb == null) return 0;
    if (va == null) return 1; // nulls last regardless of direction
    if (vb == null) return -1;
    let cmp: number;
    if (typeof va === "number" && typeof vb === "number") {
      cmp = va - vb;
    } else {
      cmp = valueText(va).localeCompare(valueText(vb), undefined, {
        numeric: true,
        sensitivity: "base",
      });
    }
    return desc ? -cmp : cmp;
  });
  return sorted;
}

/** Distinct display values of a column (stringified, deduped, capped). */
export function distinctValues<T>(
  rows: T[],
  accessor: (row: T) => unknown,
  cap = 50,
): string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    const text = valueText(accessor(row));
    if (text) seen.add(text);
    if (seen.size >= cap) break;
  }
  return [...seen].sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }),
  );
}
