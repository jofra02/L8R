import type { AssetTypeDef, AssetTypeField } from "@/api/types";

// Rendering strategy for one attribute value. Classification is driven by
// the RUNTIME shape, never the field definition alone: sensitive fields
// arrive redacted as the string "***" regardless of their declared type,
// and open_attributes/legacy keys have no definition at all.
export type AttrKind = "scalar" | "chips" | "objectArray" | "flatObject" | "json";

export interface AttrEntry {
  key: string;
  label: string;
  fieldDef?: AssetTypeField;
  value: unknown;
  kind: AttrKind;
}

const isPrimitive = (v: unknown): boolean =>
  v === null || v === undefined || ["string", "number", "boolean"].includes(typeof v);

const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

export function classifyValue(value: unknown): AttrKind {
  if (isPrimitive(value)) return "scalar";
  if (Array.isArray(value)) {
    if (value.length === 0 || value.every(isPrimitive)) return "chips";
    if (value.every(isPlainObject)) return "objectArray";
    return "json";
  }
  if (isPlainObject(value)) {
    return Object.values(value).every(isPrimitive) ? "flatObject" : "json";
  }
  return "json";
}

// Definition-declared keys first (in schema order, with labels), then
// unknown keys (open_attributes / legacy) in insertion order.
export function orderedEntries(
  attributes: Record<string, unknown>,
  typeDef?: AssetTypeDef,
): AttrEntry[] {
  const entries: AttrEntry[] = [];
  const seen = new Set<string>(["legacy_role"]);
  for (const f of typeDef?.fields ?? []) {
    if (f.key in attributes && !seen.has(f.key)) {
      seen.add(f.key);
      entries.push({
        key: f.key,
        label: f.label ?? f.key,
        fieldDef: f,
        value: attributes[f.key],
        kind: classifyValue(attributes[f.key]),
      });
    }
  }
  for (const [key, value] of Object.entries(attributes)) {
    if (seen.has(key)) continue;
    entries.push({ key, label: key, value, kind: classifyValue(value) });
  }
  return entries;
}

// Union of row keys in first-appearance order (sub-table columns).
export function columnUnion(rows: Record<string, unknown>[]): string[] {
  const cols: string[] = [];
  const seen = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (!seen.has(key)) {
        seen.add(key);
        cols.push(key);
      }
    }
  }
  return cols;
}
