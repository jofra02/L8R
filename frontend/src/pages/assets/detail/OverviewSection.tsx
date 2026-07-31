import { PropertyGrid, type PropertyGridItem } from "@/components/common/PropertyGrid";
import { TimeAgo } from "@/components/common/TimeAgo";
import type { Asset } from "@/api/types";

/** Legacy field block, still used by IntegrationSection's config card. */
export function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs text-text-muted">{label}</p>
      <p className="text-sm text-text-primary mt-0.5">{value ?? "—"}</p>
    </div>
  );
}

export function OverviewSection({ asset }: { asset: Asset }) {
  const mono = (v: string | null) => v && <span className="font-mono text-xs">{v}</span>;
  const items: PropertyGridItem[] = [
    { label: "Status", value: asset.status },
    { label: "Manufacturer", value: asset.manufacturer },
    { label: "Model", value: asset.model },
    { label: "Product", value: asset.product_name },
    { label: "Serial number", value: mono(asset.serial_number) },
    { label: "IP address", value: mono(asset.ip_address) },
    { label: "FQDN", value: asset.fqdn },
    { label: "Location", value: asset.location },
    { label: "Owner", value: asset.owner },
    {
      label: "Tags",
      value: asset.tags.length ? (
        <span className="flex flex-wrap gap-1">
          {asset.tags.map((t) => (
            <span
              key={t}
              className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary"
            >
              {t}
            </span>
          ))}
        </span>
      ) : null,
    },
    { label: "Purchase date", value: asset.purchase_date },
    { label: "Warranty expires", value: asset.warranty_expires },
    { label: "End of life", value: asset.eol_date },
    { label: "Created", value: <TimeAgo date={asset.created_at} /> },
    { label: "Updated", value: <TimeAgo date={asset.updated_at} /> },
    {
      label: "External identity",
      value: asset.external_id && (
        <span className="font-mono text-xs">
          {asset.external_source}:{asset.external_id}
        </span>
      ),
    },
  ];
  return (
    <div className="bg-card border border-border rounded-lg px-5 py-2">
      <PropertyGrid items={items} />
    </div>
  );
}
