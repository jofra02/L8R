import type { Asset } from "@/api/types";

export function SyncStatusBadge({ asset }: { asset: Asset }) {
  if (!asset.managed) {
    return <span className="text-text-secondary">—</span>;
  }
  const status = asset.sync_status;
  if (status === "synced") {
    return (
      <span
        className="text-xs px-2 py-0.5 rounded bg-severity-low/15 text-severity-low"
        title={asset.last_synced_at ?? undefined}
      >
        MCP synced
      </span>
    );
  }
  if (status === "pending") {
    return (
      <span className="text-xs px-2 py-0.5 rounded bg-status-pending/15 text-status-pending">
        MCP pending
      </span>
    );
  }
  return (
    <span
      className="text-xs px-2 py-0.5 rounded bg-severity-critical/15 text-severity-critical"
      title={asset.sync_error ?? undefined}
    >
      MCP sync {status === "skipped" ? "skipped" : "error"}
    </span>
  );
}
