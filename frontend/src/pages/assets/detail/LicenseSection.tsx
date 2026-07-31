import { useMemo } from "react";
import { format } from "date-fns";
import { EmptyState } from "@/components/common/EmptyState";
import { PropertyGrid, type PropertyGridItem } from "@/components/common/PropertyGrid";
import { TimeAgo } from "@/components/common/TimeAgo";
import { InventoryDataGrid } from "@/components/grid/InventoryDataGrid";
import type { GridColumnSchema } from "@/components/grid/types";
import { cn } from "@/lib/utils";
import type { Asset, LicenseEntry } from "@/api/types";
import { useSyncedGridState } from "../workspace/store";
import type { ViewContext } from "../resource/types";

const EXPIRING_SOON_DAYS = 60;

/** Display state: the stored `state` (pure status map, no clock baked in)
 * escalated at render time by the expiry date. */
type DisplayState = "ok" | "expiring" | "expired" | "none" | "unknown";

function displayState(entry: LicenseEntry): DisplayState {
  const exp = entry.expires ? new Date(entry.expires).getTime() : null;
  if (entry.state === "expired") return "expired";
  if (exp !== null && !isNaN(exp)) {
    const now = Date.now();
    if (exp < now && entry.state !== "none") return "expired";
    if (entry.state === "ok" && exp - now < EXPIRING_SOON_DAYS * 86400_000) return "expiring";
  }
  return (entry.state as DisplayState) ?? "unknown";
}

const STATE_STYLES: Record<DisplayState, string> = {
  ok: "bg-severity-low/10 border-severity-low/30 text-severity-low",
  expiring: "bg-severity-medium/10 border-severity-medium/30 text-severity-medium",
  expired: "bg-severity-critical/10 border-severity-critical/30 text-severity-critical",
  none: "bg-elevated border-border text-text-muted",
  unknown: "bg-severity-medium/10 border-severity-medium/30 text-severity-medium",
};

function StateBadge({ entry }: { entry: LicenseEntry }) {
  const ds = displayState(entry);
  const label = ds === "expiring" ? "expiring soon" : (entry.status ?? ds);
  return (
    <span
      title={entry.status ?? undefined}
      className={cn("text-xs px-2 py-0.5 rounded border whitespace-nowrap", STATE_STYLES[ds])}
    >
      {String(label)}
    </span>
  );
}

function ExpiresCell({ entry }: { entry: LicenseEntry }) {
  if (!entry.expires) return <span className="text-text-muted">—</span>;
  const d = new Date(entry.expires);
  if (isNaN(d.getTime())) return <span className="text-text-secondary">{entry.expires}</span>;
  const past = d.getTime() < Date.now();
  const soon = !past && d.getTime() - Date.now() < EXPIRING_SOON_DAYS * 86400_000;
  return (
    <span
      className={cn(
        "text-xs tabular-nums",
        past ? "text-severity-critical" : soon ? "text-severity-medium" : "text-text-secondary",
      )}
    >
      {format(d, "yyyy-MM-dd")} · <TimeAgo date={entry.expires} />
    </span>
  );
}

interface LicenseSectionProps {
  asset: Asset;
  ctx: ViewContext;
}

/** Normalized license inventory of one asset: summary property grid +
 * filterable grid over `attributes.licenses` (deterministic backend
 * normalization; the tab never parses vendor blobs itself). */
export function LicenseSection({ asset, ctx }: LicenseSectionProps) {
  const [gridState, setGridState] = useSyncedGridState(`${ctx.stateKeyPrefix}|license`, false, {
    pageSize: 50,
  });

  const licenses = useMemo(
    () => (Array.isArray(asset.attributes["licenses"]) ? (asset.attributes["licenses"] as LicenseEntry[]) : []),
    [asset.attributes],
  );

  // license_capacity classes not already present as seat entries become
  // synthetic capacity rows (dashboard-only consoles report capacity in a
  // separate attribute; both are backend-normalized — no vendor parsing).
  const rows = useMemo<LicenseEntry[]>(() => {
    const cap = asset.attributes["license_capacity"];
    if (!cap || typeof cap !== "object" || Array.isArray(cap)) return licenses;
    const covered = new Set(
      licenses
        .filter((e) => e.seats)
        .flatMap((e) => {
          const k = e.key.toLowerCase();
          const suffix = k.includes("/") ? k.split("/").pop()! : k;
          return [k, suffix];
        }),
    );
    const synthetic: LicenseEntry[] = [];
    for (const [name, v] of Object.entries(cap as Record<string, unknown>)) {
      if (!v || typeof v !== "object" || Array.isArray(v)) continue; // scalar counters
      if (covered.has(name.toLowerCase())) continue;
      const seats = v as { used?: number | null; max?: number | null };
      synthetic.push({
        key: `capacity:${name}`,
        label: `${name.charAt(0).toUpperCase()}${name.slice(1)} Seats`,
        category: "capacity",
        status: "active",
        state: "ok",
        expires: null,
        entitlement: null,
        seats: { used: seats.used ?? null, max: seats.max ?? null },
        version: null,
        last_update: null,
        details: {},
      });
    }
    return synthetic.length ? [...licenses, ...synthetic] : licenses;
  }, [licenses, asset.attributes]);

  const summaryItems = useMemo<PropertyGridItem[]>(() => {
    const counts: Record<DisplayState, number> = { ok: 0, expiring: 0, expired: 0, none: 0, unknown: 0 };
    let nextExpiry: LicenseEntry | null = null;
    const now = Date.now();
    for (const e of rows) {
      counts[displayState(e)] += 1;
      if (e.expires) {
        const t = new Date(e.expires).getTime();
        if (!isNaN(t) && t > now && (nextExpiry === null || t < new Date(nextExpiry.expires!).getTime())) {
          nextExpiry = e;
        }
      }
    }
    const registration = rows.find((e) => e.category === "registration");
    const capacity = rows.filter((e) => e.seats && (e.seats.max ?? 0) > 0);
    const items: PropertyGridItem[] = [
      {
        label: "Entitlements",
        value: (
          <span className="flex flex-wrap gap-1.5">
            {(["ok", "expiring", "expired", "none"] as DisplayState[])
              .filter((s) => counts[s] > 0)
              .map((s) => (
                <span key={s} className={cn("text-xs px-2 py-0.5 rounded border", STATE_STYLES[s])}>
                  {counts[s]} {s === "ok" ? "active" : s === "expiring" ? "expiring soon" : s}
                </span>
              ))}
            {counts.unknown > 0 && (
              <span className={cn("text-xs px-2 py-0.5 rounded border", STATE_STYLES.unknown)}>
                {counts.unknown} unknown
              </span>
            )}
          </span>
        ),
      },
      {
        label: "Next expiry",
        value: nextExpiry && (
          <span>
            {nextExpiry.label} · <ExpiresCell entry={nextExpiry} />
          </span>
        ),
      },
    ];
    if (registration) {
      const account = registration.details["account"] ?? registration.details["customer"];
      const company = registration.details["company"];
      items.push({
        label: "Registration",
        value: (
          <span className="flex items-center gap-2 flex-wrap">
            <StateBadge entry={registration} />
            {account != null && <span className="font-mono text-xs">{String(account)}</span>}
            {company != null && <span className="text-xs text-text-secondary">({String(company)})</span>}
          </span>
        ),
      });
    }
    const licType = asset.attributes["license_type"];
    if (typeof licType === "string" && licType) {
      items.push({ label: "License type", value: licType });
    }
    const features = asset.attributes["license_features"];
    if (Array.isArray(features) && features.length > 0) {
      items.push({
        label: "Features",
        value: (
          <span className="flex flex-wrap gap-1">
            {features.map((f) => (
              <span
                key={String(f)}
                className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary"
              >
                {String(f)}
              </span>
            ))}
          </span>
        ),
      });
    }
    for (const cap of capacity.slice(0, 4)) {
      items.push({
        label: cap.label,
        value: (
          <span className="tabular-nums">
            {cap.seats!.used ?? 0} / {cap.seats!.max ?? 0}
          </span>
        ),
      });
    }
    return items;
  }, [rows, asset.attributes]);

  const columns = useMemo<GridColumnSchema<LicenseEntry>[]>(
    () => [
      { key: "label", header: "Feature", sortable: true, filterable: true, width: 230 },
      { key: "category", header: "Category", type: "badge", sortable: true, filterable: true, width: 130 },
      {
        key: "state",
        header: "Status",
        sortable: true,
        filterable: true,
        width: 140,
        accessor: (r) => displayState(r),
        render: (r) => <StateBadge entry={r} />,
      },
      {
        key: "expires",
        header: "Expires",
        sortable: true,
        width: 190,
        accessor: (r) => r.expires,
        render: (r) => <ExpiresCell entry={r} />,
      },
      { key: "entitlement", header: "Entitlement", type: "code", sortable: true, filterable: true, width: 110 },
      {
        key: "seats",
        header: "Seats",
        width: 100,
        accessor: (r) => (r.seats ? `${r.seats.used ?? 0} / ${r.seats.max ?? 0}` : null),
        render: (r) =>
          r.seats ? (
            <span className="tabular-nums text-text-secondary">
              {r.seats.used ?? 0} / {r.seats.max ?? 0}
            </span>
          ) : (
            <span className="text-text-muted">—</span>
          ),
      },
      { key: "version", header: "Version", type: "code", width: 110, defaultHidden: true },
      { key: "last_update", header: "Last update", type: "timeago", sortable: true, width: 120, defaultHidden: true },
    ],
    [],
  );

  if (rows.length === 0) {
    const hasRaw =
      asset.attributes["license_status"] != null ||
      asset.attributes["license_type"] != null ||
      asset.attributes["license_expiration"] != null;
    return (
      <EmptyState
        title={hasRaw ? "License data not normalized yet" : "No license data"}
        message={
          hasRaw
            ? "Raw license attributes exist but the normalized inventory is missing — run \"Enrich now\" to collect it."
            : "Enrichment has not reported licensing information for this asset."
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="bg-card border border-border rounded-lg px-5 py-2">
        <PropertyGrid columns={2} items={summaryItems} />
      </div>
      <div className="bg-card border border-border rounded-lg">
        <InventoryDataGrid<LicenseEntry>
          gridId="asset.licenses"
          columns={columns}
          data={rows}
          mode="client"
          state={gridState}
          onStateChange={setGridState}
          getRowId={(r) => r.key}
          emptyMessage="No license entries"
          exportFileName={`${asset.name}-licenses`}
        />
      </div>
    </div>
  );
}
