/** Generic navigable-resource contract for the hierarchical explorer.
 *
 * Core components (shell, workspace, breadcrumb, grids) only speak this
 * interface — adding a resource type is one adapter file + a registry
 * call, never a core change.
 */
import type { ComponentType, ReactNode } from "react";

export interface ResourceRef {
  /** Adapter key: "asset", "subitem", ... */
  type: string;
  id: string;
  /** Root asset scope — every inventory resource lives under one asset
   * (API path prefix + tab identity root). */
  assetId: string;
}

export interface ResourceViewDescriptor {
  id: string;
  label: string;
}

export interface ResourceBreadcrumbSegment {
  label: string;
  /** Workspace-relative path (after /assets); "" = the master list.
   * Present on navigable ancestors, absent on the current resource. */
  afterPath?: string;
}

export interface ResourceModel<T = unknown> {
  ref: ResourceRef;
  name: string;
  typeLabel: string;
  /** Inline badge nodes rendered next to the name (state, source, ...). */
  badges?: ReactNode;
  /** Secondary identity line under the name (ref · id). */
  metaLine?: ReactNode;
  deleted?: boolean;
  /** Root-first ancestor chain, excluding the resource itself. */
  ancestors: ResourceBreadcrumbSegment[];
  raw: T;
}

export interface ViewContext {
  /** Whether the panel hosting this view is the active workspace tab
   * (controls URL mirroring of grid state). */
  active: boolean;
  /** Grid-state key prefix for this resource ("<token>|<path>"). */
  stateKeyPrefix: string;
}

export interface ResourceAdapter<T = unknown> {
  type: string;
  /** Hook: resolve the resource. Called from a component keyed by
   * type:id, so hook order is stable. */
  useResource: (ref: ResourceRef) => {
    model?: ResourceModel<T>;
    isLoading: boolean;
    error?: unknown;
  };
  /** Workspace-relative path (after /assets) for this resource/view. */
  buildPath: (ref: ResourceRef, view?: string) => string;
  /** Capability-driven view tabs (e.g. hide Discovered inventory without children). */
  views: (model: ResourceModel<T>) => ResourceViewDescriptor[];
  renderView: (view: string, model: ResourceModel<T>, ctx: ViewContext) => ReactNode;
  /** Contextual action buttons (edit/delete/enrich/...); omitted = read-only. */
  Actions?: ComponentType<{ model: ResourceModel<T>; onDeleted?: () => void }>;
}
