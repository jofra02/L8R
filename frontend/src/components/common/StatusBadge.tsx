import { cn } from "@/lib/utils";
import { SEVERITY_COLORS, STATUS_COLORS, DECISION_COLORS, ROLE_COLORS } from "@/lib/constants";

type BadgeType = "severity" | "status" | "decision" | "role";

interface StatusBadgeProps {
  value: string | null | undefined;
  type: BadgeType;
  className?: string;
}

const COLOR_MAPS: Record<BadgeType, Record<string, string>> = {
  severity: SEVERITY_COLORS,
  status: STATUS_COLORS,
  decision: DECISION_COLORS,
  role: ROLE_COLORS,
};

export function StatusBadge({ value, type, className }: StatusBadgeProps) {
  if (!value) return <span className="text-text-muted text-xs">-</span>;

  const colorMap = COLOR_MAPS[type];
  const colors = colorMap[value] ?? "bg-elevated text-text-secondary border-border";

  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border",
        colors,
        className,
      )}
    >
      {value}
    </span>
  );
}
