import type { Asset, AssetTypeDef } from "@/api/types";
import { AttributeExplorer } from "./AttributeExplorer";
import type { ViewContext } from "../resource/types";

function ProvenanceChip({ asset, attrKey }: { asset: Asset; attrKey: string }) {
  const p = asset.provenance[`attributes.${attrKey}`];
  if (p?.source === "discovered") {
    return (
      <span title={p.updated_at} className="text-xs px-2 py-0.5 rounded bg-accent/15 text-accent">
        discovered
      </span>
    );
  }
  return (
    <span
      title={p?.updated_at}
      className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-muted"
    >
      manual
    </span>
  );
}

/** Asset attributes = the generic AttributeExplorer + per-field provenance
 * chips (manual vs discovered, from the enrichment engine). */
export function SmartAttributes({
  asset,
  typeDef,
  ctx,
}: {
  asset: Asset;
  typeDef?: AssetTypeDef;
  ctx: ViewContext;
}) {
  return (
    <AttributeExplorer
      attributes={asset.attributes}
      typeDef={typeDef}
      ctx={ctx}
      suffixFor={(key) => <ProvenanceChip asset={asset} attrKey={key} />}
    />
  );
}
