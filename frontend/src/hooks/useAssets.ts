import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  createAsset,
  createAssetProduct,
  createAssetRelation,
  deleteAsset,
  deleteAssetProduct,
  deleteAssetRelation,
  enrichAsset,
  getAsset,
  getAssetHistory,
  getAssetSubitem,
  listAssetProducts,
  listAssetRelations,
  listAssets,
  listAssetSubitems,
  listAssetSyncRuns,
  listAssetTypes,
  listGlobalAssets,
  listMcpPacks,
  renameAssetProduct,
  restoreAsset,
  updateAsset,
} from "@/api/endpoints";
import type { Asset, AssetCreatePayload, AssetUpdatePayload } from "@/api/types";
import { useOptionalTenantId } from "@/contexts/TenantContext";

export const SYNC_RUN_ACTIVE_STATUSES = ["pending", "running"];
const POLL_MS = 2500;

type Filters = Record<string, string | number | boolean | undefined>;

/** Tenant scope segment for query keys. The axios client injects the tenant
 * per request (URL shell → header/param), so without this a platform admin
 * switching /t/<tenant> shells would read another tenant's cached rows. */
function useAssetScope(): string {
  return useOptionalTenantId() ?? "__global__";
}

const apiError = (e: any, fallback: string) =>
  e?.response?.data?.detail || e?.response?.data?.error || fallback;

export function useAssets(filters: Filters) {
  const scope = useAssetScope();
  return useQuery({
    queryKey: ["assets", scope, "list", filters],
    queryFn: () => listAssets(filters),
    placeholderData: keepPreviousData,
  });
}

export function useGlobalAssets(filters: Filters) {
  return useQuery({
    queryKey: ["assets", "__all__", "global", filters],
    queryFn: () => listGlobalAssets(filters),
  });
}

export function useAsset(id: string | undefined) {
  const scope = useAssetScope();
  return useQuery({
    queryKey: ["assets", scope, "detail", id],
    queryFn: () => getAsset(id!),
    enabled: !!id,
  });
}

export function useAssetTypes() {
  return useQuery({
    queryKey: ["assets", "types"],
    queryFn: listAssetTypes,
    staleTime: 5 * 60_000,
  });
}

export function useAssetProducts(includeUsage = false) {
  return useQuery({
    queryKey: ["assets", "products", includeUsage],
    queryFn: () => listAssetProducts(includeUsage),
    staleTime: 5 * 60_000,
  });
}

export function useCreateAssetProduct() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => createAssetProduct(name),
    onSuccess: (product) => {
      toast.success(`Product "${product.name}" created`);
      queryClient.invalidateQueries({ queryKey: ["assets", "products"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to create product")),
  });
}

export function useRenameAssetProduct() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameAssetProduct(id, name),
    onSuccess: ({ product, assets_updated }) => {
      toast.success(
        assets_updated > 0
          ? `Product renamed to "${product.name}" — ${assets_updated} asset(s) updated`
          : `Product renamed to "${product.name}"`,
      );
      // Rename propagates to assets across tenants — refresh everything.
      queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to rename product")),
  });
}

export function useDeleteAssetProduct() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteAssetProduct(id),
    onSuccess: () => {
      toast.success("Product deleted");
      queryClient.invalidateQueries({ queryKey: ["assets", "products"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to delete product")),
  });
}

export function useMcpPacks(enabled: boolean) {
  const scope = useAssetScope();
  return useQuery({
    queryKey: ["assets", scope, "mcp-packs"],
    queryFn: listMcpPacks,
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useAssetRelations(id: string | undefined) {
  const scope = useAssetScope();
  return useQuery({
    queryKey: ["assets", scope, "relations", id],
    queryFn: () => listAssetRelations(id!),
    enabled: !!id,
  });
}

export function useAssetHistory(id: string | undefined, page: number, pageSize: number) {
  const scope = useAssetScope();
  return useQuery({
    queryKey: ["assets", scope, "history", id, page, pageSize],
    queryFn: () => getAssetHistory(id!, { page, page_size: pageSize }),
    enabled: !!id,
  });
}

export function useAssetSyncRuns(id: string | undefined, page: number, pageSize: number) {
  const scope = useAssetScope();
  return useQuery({
    queryKey: ["assets", scope, "sync-runs", id, page, pageSize],
    queryFn: () => listAssetSyncRuns(id!, { page, page_size: pageSize }),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data?.items?.some((r) => SYNC_RUN_ACTIVE_STATUSES.includes(r.status))
        ? POLL_MS
        : false,
  });
}

export function useAssetSubitems(
  id: string | undefined,
  page: number,
  pageSize: number,
  filters: Filters = {},
) {
  const scope = useAssetScope();
  return useQuery({
    queryKey: ["assets", scope, "subitems", id, page, pageSize, filters],
    queryFn: ({ signal }) => listAssetSubitems(id!, { ...filters, page, page_size: pageSize }, signal),
    enabled: !!id,
    placeholderData: keepPreviousData,
  });
}

/** One subitem + its ancestor chain (deep-link breadcrumb reconstruction). */
export function useAssetSubitem(assetId: string | undefined, subitemId: string | undefined) {
  const scope = useAssetScope();
  return useQuery({
    queryKey: ["assets", scope, "subitem", assetId, subitemId],
    queryFn: ({ signal }) => getAssetSubitem(assetId!, subitemId!, signal),
    enabled: !!assetId && !!subitemId,
  });
}

/** Direct children of a hierarchy node: parentSubitemId "root" = top-level
 * rows under the asset, otherwise children of that subitem. */
export function useAssetSubitemChildren(
  assetId: string | undefined,
  parentSubitemId: string,
  filters: Filters,
) {
  const scope = useAssetScope();
  return useQuery({
    queryKey: ["assets", scope, "subitems", assetId, "children", parentSubitemId, filters],
    queryFn: ({ signal }) =>
      listAssetSubitems(assetId!, { ...filters, parent_subitem_id: parentSubitemId }, signal),
    enabled: !!assetId,
    placeholderData: keepPreviousData,
  });
}

function reportGatewaySync(asset: Asset, successMessage: string) {
  const sync = asset.gateway_sync;
  if (!sync) {
    toast.success(successMessage);
    return;
  }
  if (sync.status === "error") {
    toast.warning(`Saved, but gateway sync failed: ${sync.error ?? "unknown error"}`);
  } else if (sync.status === "skipped") {
    toast.warning("Saved. Gateway sync skipped (not configured).");
  } else {
    for (const w of sync.warnings ?? []) toast.warning(w);
    toast.success(`${successMessage} — device synced to gateway`);
  }
}

export function useCreateAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AssetCreatePayload) => createAsset(body),
    onSuccess: (asset) => {
      reportGatewaySync(asset, "Asset created");
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      queryClient.invalidateQueries({ queryKey: ["inventory"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to create asset")),
  });
}

export function useUpdateAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AssetUpdatePayload }) => updateAsset(id, body),
    onSuccess: (asset) => {
      reportGatewaySync(asset, "Asset updated");
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      queryClient.invalidateQueries({ queryKey: ["inventory"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to update asset")),
  });
}

export function useDeleteAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteAsset(id),
    onSuccess: () => {
      toast.success("Asset deleted");
      queryClient.invalidateQueries({ queryKey: ["assets"] });
      queryClient.invalidateQueries({ queryKey: ["inventory"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to delete asset")),
  });
}

export function useRestoreAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => restoreAsset(id),
    onSuccess: () => {
      toast.success("Asset restored");
      queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to restore asset")),
  });
}

export function useEnrichAsset() {
  const queryClient = useQueryClient();
  const scope = useAssetScope();
  return useMutation({
    mutationFn: (id: string) => enrichAsset(id),
    onSuccess: () => {
      toast.success("Enrichment run queued");
      queryClient.invalidateQueries({ queryKey: ["assets", scope, "sync-runs"] });
      queryClient.invalidateQueries({ queryKey: ["assets", scope, "subitems"] });
      queryClient.invalidateQueries({ queryKey: ["assets", scope, "detail"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to queue enrichment")),
  });
}

export function useCreateRelation(assetId: string) {
  const queryClient = useQueryClient();
  const scope = useAssetScope();
  return useMutation({
    mutationFn: (body: { target_asset_id: string; relation_type: string; direction?: "out" | "in" }) =>
      createAssetRelation(assetId, body),
    onSuccess: () => {
      toast.success("Relation created");
      queryClient.invalidateQueries({ queryKey: ["assets", scope, "relations"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to create relation")),
  });
}

export function useDeleteRelation() {
  const queryClient = useQueryClient();
  const scope = useAssetScope();
  return useMutation({
    mutationFn: (relationId: number) => deleteAssetRelation(relationId),
    onSuccess: () => {
      toast.success("Relation removed");
      queryClient.invalidateQueries({ queryKey: ["assets", scope, "relations"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to remove relation")),
  });
}
