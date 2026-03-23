export const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-severity-critical/15 text-severity-critical border-severity-critical/30",
  high: "bg-severity-high/15 text-severity-high border-severity-high/30",
  medium: "bg-severity-medium/15 text-severity-medium border-severity-medium/30",
  low: "bg-severity-low/15 text-severity-low border-severity-low/30",
};

export const STATUS_COLORS: Record<string, string> = {
  running: "bg-status-running/15 text-status-running border-status-running/30",
  pending: "bg-status-pending/15 text-status-pending border-status-pending/30",
  completed: "bg-status-completed/15 text-status-completed border-status-completed/30",
  failed: "bg-status-failed/15 text-status-failed border-status-failed/30",
  error: "bg-status-failed/15 text-status-failed border-status-failed/30",
};

export const DECISION_COLORS: Record<string, string> = {
  resolved: "bg-status-completed/15 text-status-completed border-status-completed/30",
  escalate: "bg-severity-high/15 text-severity-high border-severity-high/30",
  needs_human: "bg-severity-medium/15 text-severity-medium border-severity-medium/30",
  blocked: "bg-status-failed/15 text-status-failed border-status-failed/30",
};

export const PROFILE_COLORS: Record<string, string> = {
  "Super Admin": "bg-purple-500/15 text-purple-400 border-purple-500/30",
  "Super Admin Readonly": "bg-blue-500/15 text-blue-400 border-blue-500/30",
  "Tenant Admin": "bg-accent/15 text-accent border-accent/30",
};

export const ROLE_COLORS: Record<string, string> = {
  platform_admin: "bg-purple-500/15 text-purple-400 border-purple-500/30",
  tenant_admin: "bg-accent/15 text-accent border-accent/30",
  operator: "bg-status-completed/15 text-status-completed border-status-completed/30",
  viewer: "bg-text-secondary/15 text-text-secondary border-text-secondary/30",
};

export const ROLE_HIERARCHY = ["viewer", "operator", "tenant_admin", "platform_admin"] as const;

export const ROUTES = {
  LOGIN: "/login",
  CHANGE_PASSWORD: "/change-password",
  // Global view
  GLOBAL_DASHBOARD: "/global",
  GLOBAL_TENANTS: "/global/tenants",
  GLOBAL_TENANT_DETAIL: "/global/tenants/:id",
  GLOBAL_TICKETS: "/global/tickets",
  GLOBAL_USERS: "/global/users",
  GLOBAL_PROFILES: "/global/profiles",
  // Tenant view (relative to /t/:tenantId)
  DASHBOARD: "/",
  TICKETS: "/tickets",
  TICKET_DETAIL: "/tickets/:id",
  RUNS: "/runs",
  RUN_STATS: "/runs/stats",
  RUN_DETAIL: "/runs/:id",
  AUDIT_LOGS: "/audit/logs",
  TOOL_CALLS: "/audit/tool-calls",
  INVENTORY: "/inventory",
  API_KEYS: "/settings/keys",
  USERS: "/settings/users",
  PROFILES: "/settings/profiles",
} as const;

export const MODE_OPTIONS = ["incident", "change", "validation", "inquiry"] as const;
export const SEVERITY_OPTIONS = ["low", "medium", "high", "critical"] as const;
export const STATUS_OPTIONS = ["pending", "running", "completed", "failed", "error"] as const;
