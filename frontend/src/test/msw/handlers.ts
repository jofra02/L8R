import { http, HttpResponse } from "msw";
import { fixtures, type SubitemRow } from "./fixtures";
import type { Asset } from "@/api/types";

/** Emulates the Platform API contract used by the inventory module:
 * CSV multi-value filters (exact IN for enums, OR-of-substring for free
 * text), `-key` sort convention, offset pagination, nested subitems with
 * `parent_subitem_id` (`root` sentinel) and by-id detail with ancestors. */

const API = "/api/v1";

function csv(value: string | null): string[] {
  if (!value) return [];
  return value.split(",").map((v) => v.trim()).filter(Boolean);
}

function text(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function matchExact(row: Record<string, unknown>, key: string, tokens: string[]): boolean {
  if (tokens.length === 0) return true;
  return tokens.includes(text(row[key]));
}

function matchLike(row: Record<string, unknown>, key: string, tokens: string[]): boolean {
  if (tokens.length === 0) return true;
  const v = text(row[key]).toLowerCase();
  return tokens.some((t) => v.includes(t.toLowerCase()));
}

function sortRows<T extends Record<string, unknown>>(rows: T[], sort: string | null): T[] {
  if (!sort) return rows;
  const desc = sort.startsWith("-");
  const key = desc ? sort.slice(1) : sort;
  const sorted = [...rows].sort((a, b) => text(a[key]).localeCompare(text(b[key]), undefined, { numeric: true }));
  return desc ? sorted.reverse() : sorted;
}

function paginate<T>(rows: T[], params: URLSearchParams) {
  const page = Math.max(1, Number(params.get("page") ?? 1));
  const pageSize = Math.max(1, Number(params.get("page_size") ?? 25));
  return {
    items: rows.slice((page - 1) * pageSize, page * pageSize),
    total: rows.length,
    page,
    page_size: pageSize,
    total_pages: rows.length ? Math.ceil(rows.length / pageSize) : 0,
  };
}

const ASSET_EXACT = ["asset_type", "status", "criticality", "sync_status"];
const ASSET_LIKE = ["name", "product_name", "model", "manufacturer", "ip_address", "serial_number", "owner"];

function filterAssets(params: URLSearchParams): Asset[] {
  let rows = fixtures.assets.filter((a) => !a.deleted_at || params.get("include_deleted") === "true");
  for (const key of ASSET_EXACT) {
    const tokens = csv(params.get(key));
    rows = rows.filter((r) => matchExact(r as unknown as Record<string, unknown>, key, tokens));
  }
  for (const key of ASSET_LIKE) {
    const tokens = csv(params.get(key));
    rows = rows.filter((r) => matchLike(r as unknown as Record<string, unknown>, key, tokens));
  }
  const q = params.get("q");
  if (q) {
    const needle = q.toLowerCase();
    rows = rows.filter((r) =>
      [r.name, r.ref, r.product_name, r.model, r.serial_number, r.ip_address]
        .some((v) => text(v).toLowerCase().includes(needle)),
    );
  }
  return rows;
}

function childrenCount(id: string): number {
  return fixtures.subitems.filter((s) => s.parent_subitem_id === id).length;
}

function withCounts(row: SubitemRow): SubitemRow {
  return { ...row, children_count: childrenCount(row.id) };
}

function ancestorsOf(row: SubitemRow): Array<{ id: string; name: string; kind: string }> {
  const chain: Array<{ id: string; name: string; kind: string }> = [];
  let current: SubitemRow | undefined = row;
  for (let depth = 0; depth < 16; depth++) {
    const parentId: string | null = current?.parent_subitem_id ?? null;
    if (!parentId) break;
    current = fixtures.subitems.find((s) => s.id === parentId);
    if (!current) break;
    chain.unshift({ id: current.id, name: current.name, kind: current.kind });
  }
  return chain;
}

export const handlers = [
  http.get(`${API}/assets/types`, () => HttpResponse.json(fixtures.types)),

  http.get(`${API}/assets/products`, () => HttpResponse.json([])),

  http.get(`${API}/assets`, ({ request }) => {
    const params = new URL(request.url).searchParams;
    const rows = sortRows(
      filterAssets(params) as unknown as Record<string, unknown>[],
      params.get("sort"),
    ) as unknown as Asset[];
    return HttpResponse.json(paginate(rows, params));
  }),

  http.get(`${API}/assets/:assetId/subitems/:subitemId`, ({ params }) => {
    const row = fixtures.subitems.find(
      (s) => s.id === params["subitemId"] && s.parent_asset_id === params["assetId"],
    );
    if (!row) return HttpResponse.json({ detail: "subitem_not_found" }, { status: 404 });
    return HttpResponse.json({ ...withCounts(row), ancestors: ancestorsOf(row) });
  }),

  http.get(`${API}/assets/:assetId/subitems`, ({ request, params }) => {
    const search = new URL(request.url).searchParams;
    let rows = fixtures.subitems.filter((s) => s.parent_asset_id === params["assetId"]);

    const parent = search.get("parent_subitem_id");
    if (parent === "root") rows = rows.filter((s) => s.parent_subitem_id === null);
    else if (parent) rows = rows.filter((s) => s.parent_subitem_id === parent);

    for (const key of ["kind", "state", "source"]) {
      const tokens = csv(search.get(key));
      rows = rows.filter((r) => matchExact(r as unknown as Record<string, unknown>, key, tokens));
    }
    for (const key of ["name", "external_id"]) {
      const tokens = csv(search.get(key));
      rows = rows.filter((r) => matchLike(r as unknown as Record<string, unknown>, key, tokens));
    }
    const q = search.get("q");
    if (q) {
      const needle = q.toLowerCase();
      rows = rows.filter(
        (r) => r.name.toLowerCase().includes(needle) || r.external_id.toLowerCase().includes(needle),
      );
    }
    const absent = search.get("absent");
    if (absent !== null) rows = rows.filter((r) => r.absent === (absent === "true"));

    rows = sortRows(
      rows as unknown as Record<string, unknown>[],
      search.get("sort") ?? "name",
    ) as unknown as SubitemRow[];
    return HttpResponse.json(paginate(rows.map(withCounts), search));
  }),

  http.get(`${API}/assets/:assetId/relations`, () => HttpResponse.json([])),

  http.get(`${API}/assets/:assetId/history`, ({ request }) =>
    HttpResponse.json(paginate([], new URL(request.url).searchParams)),
  ),

  http.get(`${API}/assets/:assetId/sync-runs`, ({ request }) =>
    HttpResponse.json(paginate([], new URL(request.url).searchParams)),
  ),

  http.get(`${API}/assets/:assetId`, ({ params }) => {
    const asset = fixtures.assets.find((a) => a.id === params["assetId"]);
    if (!asset) return HttpResponse.json({ detail: "asset_not_found" }, { status: 404 });
    return HttpResponse.json(asset);
  }),
];
