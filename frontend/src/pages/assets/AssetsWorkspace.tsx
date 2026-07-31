import { useCallback, useEffect, useMemo } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { List, Server } from "lucide-react";
import { toast } from "sonner";
import { TabStrip, type TabDescriptor } from "@/components/common/TabStrip";
import { EmptyState } from "@/components/common/EmptyState";
import { cn } from "@/lib/utils";
import { useTenantId } from "@/contexts/TenantContext";
import { useAsset, useAssetSubitem } from "@/hooks/useAssets";
import { AssetListPanel } from "./AssetListPanel";
import { getAdapter } from "./resource/registry";
import { ResourceDetailShell } from "./resource/ResourceDetailShell";
import type { ResourceRef } from "./resource/types";
import { WorkspaceContext, useWorkspace, type WorkspaceApi } from "./workspace/WorkspaceContext";
import {
  LIST_TOKEN,
  locationParams,
  tokenLocation,
  tokenRoot,
  useSyncedGridState,
  useWorkspaceStore,
} from "./workspace/store";
// Side-effect imports: adapters register themselves.
import "./resource/assetAdapter";
import "./resource/subitemAdapter";

interface ParsedPath {
  assetId?: string;
  subitemId?: string;
  view: string;
}

/** Path grammar (after /assets):
 *   ""                                  → master list
 *   :assetId[/:view]                    → asset detail
 *   :assetId/sub/:subitemId[/:view]     → subitem detail (any depth: the
 *                                         leaf id is enough — ancestors
 *                                         come from the API)
 */
export function parseAssetsPath(splat: string): ParsedPath {
  const parts = splat.split("/").filter(Boolean);
  const assetId = parts[0];
  if (!assetId) return { view: "" };
  if (parts[1] === "sub" && parts[2]) {
    return { assetId, subitemId: parts[2], view: parts[3] ?? "overview" };
  }
  return { assetId, view: parts[1] ?? "overview" };
}

function splitLocation(loc: string): { path: string; query: string } {
  const idx = loc.indexOf("?");
  if (idx < 0) return { path: loc, query: "" };
  return { path: loc.slice(0, idx), query: loc.slice(idx + 1) };
}

/** Tab title resolved from the shared query cache. */
function AssetTabLabel({ token }: { token: string }) {
  const root = tokenRoot(token);
  const subitemId = token.split(".")[1];
  const { data: asset } = useAsset(root);
  const { data: subitem } = useAssetSubitem(subitemId ? root : undefined, subitemId);
  if (subitemId) return <>{subitem?.name ?? `${subitemId.slice(0, 8)}…`}</>;
  return <>{asset?.name ?? `${root.slice(0, 8)}…`}</>;
}

function ResourceTabPanel({
  token,
  active,
  currentPath,
}: {
  token: string;
  active: boolean;
  currentPath: ParsedPath;
}) {
  const { closeTab } = useWorkspace();
  const storedLocation = useWorkspaceStore(
    (s) => s.tabs.find((t) => t.token === token)?.location,
  );
  const loc = active
    ? currentPath
    : parseAssetsPath(splitLocation(storedLocation ?? tokenLocation(token)).path);
  const assetId = loc.assetId ?? tokenRoot(token);
  const ref: ResourceRef = loc.subitemId
    ? { type: "subitem", id: loc.subitemId, assetId }
    : { type: "asset", id: assetId, assetId };
  const adapter = getAdapter(ref.type);
  if (!adapter) {
    return <EmptyState title="Unsupported resource" message={`No adapter registered for '${ref.type}'`} />;
  }
  return (
    <ResourceDetailShell
      key={`${ref.type}:${ref.id}`}
      adapter={adapter}
      refObj={ref}
      view={loc.view}
      active={active}
      stateKeyPrefix={`${token}|${loc.subitemId ? `${assetId}/sub/${loc.subitemId}` : assetId}`}
      onDeleted={() => closeTab(token)}
    />
  );
}

/** Master list wrapper: grid state synced with the store + URL. */
function ListPanel({ active }: { active: boolean }) {
  const { openAsset, openAssetInNewTab } = useWorkspace();
  const [gridState, setGridState] = useSyncedGridState(`${LIST_TOKEN}|`, active, {
    sort: "-created_at",
  });
  return (
    <AssetListPanel
      gridState={gridState}
      onGridStateChange={setGridState}
      onOpenAsset={(a) => openAsset(a.id)}
      onOpenAssetNewTab={(a) => openAssetInNewTab(a.id)}
    />
  );
}

/** Hierarchical assets workspace: browser-style tabs over a recursive
 * resource explorer. The URL carries the ACTIVE tab's location (path +
 * grid params) plus the open-tab list (?tabs=&active=); inactive tabs
 * keep their state in the sessionStorage-backed store. */
export function AssetsWorkspace() {
  const tenantId = useTenantId();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const routeParams = useParams();

  const splat = (routeParams["*"] ?? "").replace(/\/+$/, "");
  const parsed = parseAssetsPath(splat);

  const storeTenantId = useWorkspaceStore((s) => s.tenantId);
  const tabs = useWorkspaceStore((s) => s.tabs);

  // Tenant binding: switching /t/<tenant> shells wipes incompatible tabs.
  useEffect(() => {
    useWorkspaceStore.getState().ensureTenant(tenantId);
  }, [tenantId]);

  const urlTokens = useMemo(
    () => (searchParams.get("tabs") ?? "").split(",").filter(Boolean),
    [searchParams],
  );
  const activeParam = searchParams.get("active");

  const activeToken = useMemo(() => {
    if (!parsed.assetId) return LIST_TOKEN;
    if (activeParam && urlTokens.includes(activeParam) && tokenRoot(activeParam) === parsed.assetId) {
      return activeParam;
    }
    return urlTokens.find((t) => tokenRoot(t) === parsed.assetId) ?? parsed.assetId;
  }, [parsed.assetId, activeParam, urlTokens]);

  const openTokens = useMemo(
    () => (activeToken === LIST_TOKEN || urlTokens.includes(activeToken)
      ? urlTokens
      : [...urlTokens, activeToken]),
    [urlTokens, activeToken],
  );

  const buildSearch = useCallback(
    (tokensList: string[], activeTok: string | null, extraQuery = "") => {
      const p = new URLSearchParams(extraQuery);
      if (tokensList.length) p.set("tabs", tokensList.join(","));
      else p.delete("tabs");
      if (activeTok && activeTok !== LIST_TOKEN) p.set("active", activeTok);
      else p.delete("active");
      const s = p.toString();
      return s ? `?${s}` : "";
    },
    [],
  );

  const urlFor = useCallback(
    (afterPath: string, token: string | null, tokensList: string[], extraQuery = "") =>
      `/t/${tenantId}/assets${afterPath ? `/${afterPath}` : ""}${buildSearch(tokensList, token, extraQuery)}`,
    [tenantId, buildSearch],
  );

  // Keep URL and store consistent: register deep-linked tabs, refresh the
  // active tab's stored location on every navigation/param change.
  useEffect(() => {
    if (storeTenantId !== tenantId) return; // wait for the tenant reset
    const store = useWorkspaceStore.getState();
    const loc = `${splat}${locationParams(searchParams)}`;
    if (activeToken === LIST_TOKEN) {
      store.setListLocation(locationParams(searchParams));
      return;
    }
    const dropped = store.openTab(activeToken, loc);
    if (dropped.length) {
      toast.info(`Tab limit reached — closed ${dropped.length} oldest tab${dropped.length === 1 ? "" : "s"}`);
    }
    store.setTabLocation(activeToken, loc);
    const wanted = openTokens.filter((t) => !dropped.includes(t));
    if (!urlTokens.includes(activeToken) || dropped.length || activeParam !== activeToken) {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (wanted.length) next.set("tabs", wanted.join(","));
          else next.delete("tabs");
          next.set("active", activeToken);
          return next;
        },
        { replace: true },
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location, storeTenantId, tenantId]);

  const activateToken = useCallback(
    (token: string, tokensList: string[], push: boolean) => {
      const store = useWorkspaceStore.getState();
      if (token === LIST_TOKEN) {
        const { query } = splitLocation(store.listLocation);
        navigate(urlFor("", null, tokensList, query), { replace: !push });
        return;
      }
      const stored = store.tabs.find((t) => t.token === token)?.location ?? tokenLocation(token);
      const { path, query } = splitLocation(stored);
      navigate(urlFor(path, token, tokensList, query), { replace: !push });
    },
    [navigate, urlFor],
  );

  const openAsset = useCallback(
    (assetId: string, forceNew = false) => {
      void forceNew; // one tab per root asset; "new tab" == activate existing
      if (openTokens.includes(assetId)) {
        activateToken(assetId, openTokens, false);
        return;
      }
      const dropped = useWorkspaceStore.getState().openTab(assetId, assetId);
      if (dropped.length) {
        toast.info(`Tab limit reached — closed ${dropped.length} oldest tab${dropped.length === 1 ? "" : "s"}`);
      }
      const nextTokens = [...openTokens.filter((t) => !dropped.includes(t)), assetId];
      navigate(urlFor(assetId, assetId, nextTokens), { replace: false });
    },
    [openTokens, activateToken, navigate, urlFor],
  );

  const openSubitemInNewTab = useCallback(
    (assetId: string, subitemId: string) => {
      const token = `${assetId}.${subitemId}`;
      const afterPath = `${assetId}/sub/${subitemId}`;
      if (openTokens.includes(token)) {
        activateToken(token, openTokens, false);
        return;
      }
      const dropped = useWorkspaceStore.getState().openTab(token, afterPath);
      const nextTokens = [...openTokens.filter((t) => !dropped.includes(t)), token];
      navigate(urlFor(afterPath, token, nextTokens), { replace: false });
    },
    [openTokens, activateToken, navigate, urlFor],
  );

  const closeTab = useCallback(
    (token: string) => {
      const idx = openTokens.indexOf(token);
      const next = openTokens.filter((t) => t !== token);
      useWorkspaceStore.getState().closeTab(token);
      if (activeToken !== token) {
        setSearchParams(
          (prev) => {
            const p = new URLSearchParams(prev);
            if (next.length) p.set("tabs", next.join(","));
            else p.delete("tabs");
            return p;
          },
          { replace: true },
        );
        return;
      }
      const nextActive = idx > 0 ? (next[idx - 1] ?? LIST_TOKEN) : LIST_TOKEN;
      activateToken(nextActive, next, true);
    },
    [openTokens, activeToken, setSearchParams, activateToken],
  );

  const api: WorkspaceApi = useMemo(
    () => ({
      tenantId,
      activeToken,
      hrefFor: (afterPath, token) => {
        if (afterPath === "") {
          const { query } = splitLocation(useWorkspaceStore.getState().listLocation);
          return urlFor("", null, openTokens, query);
        }
        return urlFor(afterPath, token === undefined ? activeToken : token, openTokens);
      },
      navigateTo: (afterPath, opts) => {
        const token = afterPath === "" ? LIST_TOKEN : activeToken;
        if (token === LIST_TOKEN) {
          activateToken(LIST_TOKEN, openTokens, opts?.push ?? false);
          return;
        }
        navigate(urlFor(afterPath, token, openTokens), { replace: !opts?.push });
      },
      openAsset: (assetId) => openAsset(assetId),
      openAssetInNewTab: (assetId) => openAsset(assetId, true),
      openSubitemInNewTab,
      closeTab,
    }),
    [tenantId, activeToken, openTokens, urlFor, navigate, openAsset, openSubitemInNewTab, closeTab, activateToken],
  );

  const tabDescriptors: TabDescriptor[] = [
    { id: LIST_TOKEN, label: "Assets", icon: <List size={13} /> },
    ...openTokens.map((token) => ({
      id: token,
      label: <AssetTabLabel token={token} />,
      icon: <Server size={13} />,
      closable: true,
    })),
  ];

  // Panels for tokens known to the store (deep-linked tokens register via
  // the effect above; until then only the active one renders).
  const panelTokens = useMemo(
    () => openTokens.filter((t) => t === activeToken || tabs.some((tab) => tab.token === t)),
    [openTokens, activeToken, tabs],
  );

  return (
    <WorkspaceContext.Provider value={api}>
      <div className="space-y-4">
        {openTokens.length > 0 && (
          <TabStrip
            tabs={tabDescriptors}
            activeId={activeToken}
            onActivate={(id) => activateToken(id, openTokens, false)}
            onClose={closeTab}
          />
        )}
        {/* Panels stay mounted so view/grid/scroll state survives tab
            switches; react-query dedupes the fetches. */}
        <div className={cn(activeToken !== LIST_TOKEN && "hidden")}>
          <ListPanel active={activeToken === LIST_TOKEN} />
        </div>
        {panelTokens.map((token) => (
          <div key={token} className={cn(activeToken !== token && "hidden")}>
            <ResourceTabPanel token={token} active={activeToken === token} currentPath={parsed} />
          </div>
        ))}
      </div>
    </WorkspaceContext.Provider>
  );
}
