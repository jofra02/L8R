import { StatusBadge } from "@/components/common/StatusBadge";
import { PropertyGrid } from "@/components/common/PropertyGrid";
import { TimeAgo } from "@/components/common/TimeAgo";
import { useAsset, useAssetSubitem } from "@/hooks/useAssets";
import type { AssetSubitemDetail } from "@/api/types";
import { AttributeExplorer } from "../attributes/AttributeExplorer";
import { SubInventorySection } from "../detail/SubInventorySection";
import { registerAdapter } from "./registry";
import type {
  ResourceAdapter,
  ResourceBreadcrumbSegment,
  ResourceModel,
  ResourceRef,
} from "./types";

export interface SubitemResource {
  subitem: AssetSubitemDetail;
}

function SubitemOverview({ subitem }: { subitem: AssetSubitemDetail }) {
  return (
    <div className="bg-card border border-border rounded-lg px-5 py-2">
      <PropertyGrid
        items={[
          { label: "Kind", value: subitem.kind },
          { label: "Source", value: subitem.source },
          { label: "State", value: subitem.state },
          {
            label: "Presence",
            value: subitem.absent ? (
              <span className="text-severity-critical">absent from last scan</span>
            ) : (
              "present"
            ),
          },
          { label: "External ID", value: <span className="font-mono text-xs">{subitem.external_id}</span> },
          { label: "Direct children", value: subitem.children_count || "—" },
          {
            label: "First seen",
            value: subitem.first_seen_at && <TimeAgo date={subitem.first_seen_at} />,
          },
          {
            label: "Last seen",
            value: subitem.last_seen_at && <TimeAgo date={subitem.last_seen_at} />,
          },
          { label: "Created", value: <TimeAgo date={subitem.created_at} /> },
          { label: "Updated", value: <TimeAgo date={subitem.updated_at} /> },
          {
            label: "Promoted asset",
            value: subitem.promoted_asset_id && (
              <span className="font-mono text-xs">{subitem.promoted_asset_id}</span>
            ),
          },
        ]}
      />
    </div>
  );
}

/** Ancestor chain → breadcrumb: Assets / <asset> / Discovered inventory /
 * <node> / Discovered inventory / ... — every segment navigable, any depth.
 * Route slugs keep the historical `sub-inventory` token. */
function buildAncestors(
  ref: ResourceRef,
  subitem: AssetSubitemDetail,
  assetName: string,
): ResourceBreadcrumbSegment[] {
  const segments: ResourceBreadcrumbSegment[] = [
    { label: "Assets", afterPath: "" },
    { label: assetName, afterPath: ref.assetId },
    { label: "Discovered inventory", afterPath: `${ref.assetId}/sub-inventory` },
  ];
  for (const anc of subitem.ancestors) {
    segments.push({ label: anc.name, afterPath: `${ref.assetId}/sub/${anc.id}` });
    segments.push({
      label: "Discovered inventory",
      afterPath: `${ref.assetId}/sub/${anc.id}/sub-inventory`,
    });
  }
  return segments;
}

export const subitemAdapter: ResourceAdapter<SubitemResource> = {
  type: "subitem",

  useResource(ref: ResourceRef) {
    const { data: subitem, isLoading, error } = useAssetSubitem(ref.assetId, ref.id);
    const { data: asset } = useAsset(ref.assetId);
    if (!subitem) return { isLoading, error };
    const model: ResourceModel<SubitemResource> = {
      ref,
      name: subitem.name,
      typeLabel: subitem.kind,
      badges: (
        <>
          {subitem.state && <StatusBadge value={subitem.state} type="status" />}
          <span className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary">
            {subitem.source}
          </span>
          {subitem.absent && (
            <span className="text-xs px-2 py-0.5 rounded bg-severity-critical/15 text-severity-critical">
              absent
            </span>
          )}
        </>
      ),
      metaLine: (
        <span className="font-mono">
          {subitem.external_id} · {subitem.id}
        </span>
      ),
      ancestors: buildAncestors(ref, subitem, asset?.name ?? `${ref.assetId.slice(0, 8)}…`),
      raw: { subitem },
    };
    return { isLoading: false, model };
  },

  buildPath(ref, view) {
    const base = `${ref.assetId}/sub/${ref.id}`;
    return view && view !== "overview" ? `${base}/${view}` : base;
  },

  views(model) {
    const { subitem } = model.raw;
    return [
      { id: "overview", label: "Overview" },
      ...(Object.keys(subitem.attributes).length ? [{ id: "attributes", label: "Attributes" }] : []),
      ...(subitem.children_count > 0
        ? [{ id: "sub-inventory", label: "Discovered inventory" }]
        : []),
    ];
  },

  renderView(view, model, ctx) {
    const { subitem } = model.raw;
    switch (view) {
      case "attributes":
        return <AttributeExplorer attributes={subitem.attributes} ctx={ctx} />;
      case "sub-inventory":
        return (
          <SubInventorySection
            assetId={model.ref.assetId}
            parentSubitemId={subitem.id}
            ctx={ctx}
          />
        );
      case "overview":
      default:
        return <SubitemOverview subitem={subitem} />;
    }
  },
};

registerAdapter(subitemAdapter);
