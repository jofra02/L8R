/** Workspace tab + grid state store.
 *
 * Single source of truth for per-tab navigation state; the URL mirrors the
 * ACTIVE tab (path + grid params) so deep links, refresh and back/forward
 * work, while inactive tabs keep their state here. Persisted to
 * sessionStorage and wiped on tenant switch — tabs are tenant-bound.
 */
import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { DEFAULT_GRID_STATE, type GridState } from "@/components/grid/types";
import type { ColumnFilters } from "@/lib/columnFilters";

export const LIST_TOKEN = "__list";
export const MAX_TABS = 10;

/** Tab identity: assetId (opened from the list) or assetId.subitemId
 * (subitem opened in its own tab). Identity is what was originally opened;
 * the tab's current location changes as the user drills down. */
export interface WorkspaceTab {
  token: string;
  /** after-/assets path + "?" + grid params (never includes tabs/active). */
  location: string;
}

export function tokenRoot(token: string): string {
  return token.split(".")[0] ?? token;
}

/** Default location for a token that has no stored state (fresh deep link). */
export function tokenLocation(token: string): string {
  const [assetId, subitemId] = token.split(".");
  return subitemId ? `${assetId}/sub/${subitemId}` : (assetId ?? "");
}

interface WorkspaceStore {
  tenantId: string | null;
  tabs: WorkspaceTab[];
  /** Last location (grid params) of the master list "tab". */
  listLocation: string;
  gridState: Record<string, GridState>;
  ensureTenant: (tenantId: string) => void;
  /** Register/refresh a tab; returns tokens evicted by the MAX_TABS cap. */
  openTab: (token: string, location?: string) => string[];
  closeTab: (token: string) => void;
  setTabLocation: (token: string, location: string) => void;
  setListLocation: (location: string) => void;
  saveGridState: (key: string, state: GridState) => void;
}

export const useWorkspaceStore = create<WorkspaceStore>()(
  persist(
    (set, get) => ({
      tenantId: null,
      tabs: [],
      listLocation: "",
      gridState: {},
      ensureTenant: (tenantId) => {
        if (get().tenantId !== tenantId) {
          set({ tenantId, tabs: [], listLocation: "", gridState: {} });
        }
      },
      openTab: (token, location) => {
        const { tabs } = get();
        if (tabs.some((t) => t.token === token)) return [];
        let next = [...tabs, { token, location: location ?? tokenLocation(token) }];
        let dropped: string[] = [];
        if (next.length > MAX_TABS) {
          dropped = next.slice(0, next.length - MAX_TABS).map((t) => t.token);
          next = next.slice(next.length - MAX_TABS);
        }
        set({ tabs: next });
        return dropped;
      },
      closeTab: (token) =>
        set((s) => ({
          tabs: s.tabs.filter((t) => t.token !== token),
          gridState: Object.fromEntries(
            Object.entries(s.gridState).filter(([k]) => !k.startsWith(`${token}|`)),
          ),
        })),
      setTabLocation: (token, location) =>
        set((s) => ({
          tabs: s.tabs.map((t) => (t.token === token ? { ...t, location } : t)),
        })),
      setListLocation: (location) => set({ listLocation: location }),
      saveGridState: (key, state) =>
        set((s) => ({ gridState: { ...s.gridState, [key]: state } })),
    }),
    {
      name: "asset-workspace",
      storage: createJSONStorage(() => sessionStorage),
    },
  ),
);

// --- grid state <-> URL params (f.<col>=v1,v2  sort=-name  page=2) ---

export function parseGridParams(params: URLSearchParams): GridState | null {
  const filters: ColumnFilters = {};
  let any = false;
  for (const [k, v] of params.entries()) {
    if (k.startsWith("f.")) {
      const tokens = v.split(",").map((t) => t.trim()).filter(Boolean);
      if (tokens.length) {
        filters[k.slice(2)] = tokens;
        any = true;
      }
    }
  }
  const sort = params.get("sort") ?? undefined;
  if (sort) any = true;
  const pageRaw = Number(params.get("page") ?? "");
  const page = Number.isInteger(pageRaw) && pageRaw >= 1 ? pageRaw : 1;
  if (page > 1) any = true;
  if (!any) return null;
  return { ...DEFAULT_GRID_STATE, filters, sort, page };
}

export function writeGridParams(prev: URLSearchParams, state: GridState): URLSearchParams {
  const next = new URLSearchParams(prev);
  for (const key of [...next.keys()]) {
    if (key.startsWith("f.")) next.delete(key);
  }
  for (const [col, tokens] of Object.entries(state.filters)) {
    if (tokens.length) next.set(`f.${col}`, tokens.join(","));
  }
  if (state.sort) next.set("sort", state.sort);
  else next.delete("sort");
  if (state.page > 1) next.set("page", String(state.page));
  else next.delete("page");
  return next;
}

/** Strip workspace bookkeeping params, keeping only per-location state
 * (grid params + view sub-tabs) for storage in a tab location. */
export function locationParams(params: URLSearchParams): string {
  const kept = new URLSearchParams();
  for (const [k, v] of params.entries()) {
    if (k === "tabs" || k === "active") continue;
    kept.set(k, v);
  }
  const s = kept.toString();
  return s ? `?${s}` : "";
}

/** Controlled grid state for a workspace panel.
 *
 * Source of truth is the store (survives tab switches, keep-mounted
 * panels); when `active`, changes are mirrored to the URL with replace
 * navigation, and external URL changes (deep link, back/forward) hydrate
 * the store back. */
export function useSyncedGridState(
  key: string,
  active: boolean,
  defaults?: Partial<GridState>,
): [GridState, (next: GridState) => void] {
  const stored = useWorkspaceStore((s) => s.gridState[key]);
  const save = useWorkspaceStore((s) => s.saveGridState);
  const [searchParams, setSearchParams] = useSearchParams();
  const defaultsRef = useRef(defaults);

  const state = stored ?? { ...DEFAULT_GRID_STATE, ...defaultsRef.current };

  useEffect(() => {
    if (!active) return;
    const fromUrl = parseGridParams(searchParams);
    if (fromUrl && JSON.stringify(fromUrl) !== JSON.stringify(stored ?? null)) {
      save(key, fromUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, searchParams, key]);

  const setState = (next: GridState) => {
    save(key, next);
    if (active) {
      setSearchParams((prev) => writeGridParams(prev, next), { replace: true });
    }
  };

  return [state, setState];
}
