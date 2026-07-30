import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  createAsset,
  createAssetRelation,
  deleteAsset,
  deleteAssetRelation,
  enrichAsset,
  getAsset,
  getAssetHistory,
  listAssetRelations,
  listAssets,
  listAssetSubitems,
  listAssetSyncRuns,
  listAssetTypes,
  listGlobalAssets,
  listMcpPacks,
  restoreAsset,
  updateAsset,
} from "@/api/endpoints";
import type { Asset, AssetCreatePayload, AssetUpdatePayload } from "@/api/types";

export const SYNC_RUN_ACTIVE_STATUSES = ["pending", "running"];
const POLL_MS = 2500;

type Filters = Record<string, string | number | boolean | undefined>;

const apiError = (e: any, fallback: string) =>
  e?.response?.data?.detail || e?.response?.data?.error || fallback;

export function useAssets(filters: Filters) {
  return useQuery({
    queryKey: ["assets", "list", filters],
    queryFn: () => listAssets(filters),
  });
}

export function useGlobalAssets(filters: Filters) {
  return useQuery({
    queryKey: ["assets", "global", filters],
    queryFn: () => listGlobalAssets(filters),
  });
}

export function useAsset(id: string | undefined) {
  return useQuery({
    queryKey: ["assets", "detail", id],
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

export function useMcpPacks(enabled: boolean) {
  return useQuery({
    queryKey: ["assets", "mcp-packs"],
    queryFn: listMcpPacks,
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useAssetRelations(id: string | undefined) {
  return useQuery({
    queryKey: ["assets", "relations", id],
    queryFn: () => listAssetRelations(id!),
    enabled: !!id,
  });
}

export function useAssetHistory(id: string | undefined, page: number, pageSize: number) {
  return useQuery({
    queryKey: ["assets", "history", id, page, pageSize],
    queryFn: () => getAssetHistory(id!, { page, page_size: pageSize }),
    enabled: !!id,
  });
}

export function useAssetSyncRuns(id: string | undefined, page: number, pageSize: number) {
  return useQuery({
    queryKey: ["assets", "sync-runs", id, page, pageSize],
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
  return useQuery({
    queryKey: ["assets", "subitems", id, page, pageSize, filters],
    queryFn: () => listAssetSubitems(id!, { ...filters, page, page_size: pageSize }),
    enabled: !!id,
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
  return useMutation({
    mutationFn: (id: string) => enrichAsset(id),
    onSuccess: () => {
      toast.success("Enrichment run queued");
      queryClient.invalidateQueries({ queryKey: ["assets", "sync-runs"] });
      queryClient.invalidateQueries({ queryKey: ["assets", "subitems"] });
      queryClient.invalidateQueries({ queryKey: ["assets", "detail"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to queue enrichment")),
  });
}

export function useCreateRelation(assetId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { target_asset_id: string; relation_type: string; direction?: "out" | "in" }) =>
      createAssetRelation(assetId, body),
    onSuccess: () => {
      toast.success("Relation created");
      queryClient.invalidateQueries({ queryKey: ["assets", "relations"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to create relation")),
  });
}

export function useDeleteRelation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (relationId: number) => deleteAssetRelation(relationId),
    onSuccess: () => {
      toast.success("Relation removed");
      queryClient.invalidateQueries({ queryKey: ["assets", "relations"] });
    },
    onError: (e: any) => toast.error(apiError(e, "Failed to remove relation")),
  });
}
