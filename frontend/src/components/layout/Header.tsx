import { useLocation, Link } from "react-router-dom";
import { Shield, ChevronDown, LogOut, Building2 } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { TenantSwitcherModal } from "./TenantSwitcherModal";

interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  is_platform_admin: boolean;
  customer_id: string;
  available_tenants: string[];
}

interface HeaderProps {
  user: AuthUser | null;
  onLogout: () => void;
  mode: "global" | "tenant";
  tenantId?: string;
}

const ROUTE_LABELS: Record<string, string> = {
  "/": "Dashboard",
  "/global": "Dashboard",
  "/global/tenants": "Tenants",
  "/global/tickets": "Tickets",
  "/global/assets": "Assets",
  "/global/users": "Users",
  "/global/profiles": "Profiles",
  "/tickets": "Tickets",
  "/runs": "Runs",
  "/runs/stats": "Run Statistics",
  "/audit/logs": "Audit Logs",
  "/audit/tool-calls": "Tool Calls",
  "/assets": "Assets",
  "/inventory": "Inventory",
  "/notifications": "Notifications",
  "/settings/keys": "API Keys",
  "/settings/users": "Users",
  "/settings/profiles": "Profiles",
};

export function Header({ user, onLogout, mode, tenantId }: HeaderProps) {
  const location = useLocation();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Derive breadcrumb label — strip /t/:tenantId prefix for tenant mode
  const rawPath = location.pathname;
  const strippedPath = mode === "tenant"
    ? rawPath.replace(/^\/t\/[^/]+/, "") || "/"
    : rawPath;
  const pathSegments = strippedPath.split("/").filter(Boolean);
  const currentLabel =
    ROUTE_LABELS[strippedPath] ??
    ROUTE_LABELS[rawPath] ??
    (pathSegments.length > 0 ? pathSegments[pathSegments.length - 1] : "Dashboard");

  const logoTo = mode === "global" ? "/global" : `/t/${tenantId}`;
  const canSwitchTenants = user && (user.is_platform_admin || user.available_tenants.length > 1);

  return (
    <>
      <header className="fixed top-0 left-0 right-0 h-16 bg-sidebar border-b border-border z-50 flex items-center justify-between px-6">
        <div className="flex items-center gap-4">
          <Link to={logoTo} className="flex items-center gap-2">
            <Shield className="text-accent" size={24} />
            <span className="text-lg font-semibold text-text-primary tracking-tight">SupportAI</span>
          </Link>
          <span className="text-text-muted">/</span>
          <span className="text-sm text-text-secondary">{currentLabel}</span>
        </div>

        {user && (
          <div className="flex items-center gap-3">
            {/* Tenant/Global context indicator */}
            {mode === "global" ? (
              <span className="text-xs px-2 py-1 rounded border font-medium bg-blue-500/15 text-blue-400 border-blue-500/30">
                Global
              </span>
            ) : tenantId && (
              canSwitchTenants ? (
                <button
                  onClick={() => setSwitcherOpen(true)}
                  className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded border bg-elevated border-border text-text-secondary font-mono hover:border-accent hover:text-text-primary transition-colors"
                >
                  <Building2 size={12} />
                  {tenantId}
                  <ChevronDown size={12} />
                </button>
              ) : (
                <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded border bg-elevated border-border text-text-secondary font-mono">
                  <Building2 size={12} />
                  {tenantId}
                </span>
              )
            )}

            {user.is_platform_admin && (
              <span className="text-xs px-2 py-1 rounded border font-medium bg-purple-500/15 text-purple-400 border-purple-500/30">
                admin
              </span>
            )}

            <div className="relative" ref={dropdownRef}>
              <button
                onClick={() => setDropdownOpen(!dropdownOpen)}
                className="flex items-center gap-2 text-text-secondary hover:text-text-primary transition-colors p-1 rounded hover:bg-elevated"
              >
                <span className="text-sm">{user.display_name || user.email}</span>
                <ChevronDown size={16} />
              </button>
              {dropdownOpen && (
                <div className="absolute right-0 top-full mt-1 w-56 bg-card border border-border rounded-md shadow-lg py-1 z-50">
                  <div className="px-3 py-2 border-b border-border">
                    <p className="text-xs text-text-muted">Signed in as</p>
                    <p className="text-xs font-mono text-text-secondary truncate">{user.email}</p>
                  </div>
                  <button
                    onClick={() => {
                      setDropdownOpen(false);
                      onLogout();
                    }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:text-severity-critical hover:bg-elevated transition-colors"
                  >
                    <LogOut size={14} />
                    Sign out
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </header>

      {/* Tenant Switcher Modal */}
      {mode === "tenant" && tenantId && (
        <TenantSwitcherModal
          open={switcherOpen}
          onClose={() => setSwitcherOpen(false)}
          currentTenantId={tenantId}
        />
      )}
    </>
  );
}
