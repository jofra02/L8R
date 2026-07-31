import { createContext, useContext } from "react";

export interface WorkspaceApi {
  tenantId: string;
  activeToken: string;
  /** Absolute href for a workspace-relative path (after /assets), keeping
   * the open-tab bookkeeping params. afterPath "" = the master list. */
  hrefFor: (afterPath: string, token?: string | null) => string;
  /** Navigate within the active tab (drill-down, view switch, breadcrumb). */
  navigateTo: (afterPath: string, opts?: { push?: boolean }) => void;
  /** Open an asset: activates its tab or creates one. */
  openAsset: (assetId: string) => void;
  openAssetInNewTab: (assetId: string) => void;
  /** Open a subitem as its own workspace tab (token assetId.subitemId). */
  openSubitemInNewTab: (assetId: string, subitemId: string) => void;
  closeTab: (token: string) => void;
}

export const WorkspaceContext = createContext<WorkspaceApi | null>(null);

export function useWorkspace(): WorkspaceApi {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within AssetsWorkspace");
  return ctx;
}
