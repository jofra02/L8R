import { format } from "date-fns";
import type { AssetTypeField } from "@/api/types";

// Server-side redaction sentinel for sensitive fields (assets:manage gated).
const REDACTED = "***";

export function AttributeValue({
  value,
  fieldType,
}: {
  value: unknown;
  fieldType?: AssetTypeField["type"];
}) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-text-muted">—</span>;
  }
  if (value === REDACTED) {
    return (
      <span
        className="text-xs px-2 py-0.5 rounded bg-elevated border border-border font-mono text-text-muted"
        title="Redacted — requires assets:manage"
      >
        ***
      </span>
    );
  }
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  if (typeof value === "number") {
    return <span className="tabular-nums">{value.toLocaleString()}</span>;
  }
  if (typeof value === "string") {
    if (fieldType === "date" || fieldType === "datetime") {
      const d = new Date(value);
      if (!isNaN(d.getTime())) {
        return (
          <span title={value}>
            {format(d, fieldType === "date" ? "yyyy-MM-dd" : "yyyy-MM-dd HH:mm")}
          </span>
        );
      }
    }
    if (fieldType === "ip") return <span className="font-mono">{value}</span>;
    return <span className="break-all">{value}</span>;
  }
  return <span className="break-all">{String(value)}</span>;
}
