import { useLocation, Link } from "react-router-dom";
import { Shield, ChevronDown, LogOut } from "lucide-react";
import type { AuthContext } from "@/api/types";
import { cn } from "@/lib/utils";
import { ROLE_COLORS } from "@/lib/constants";
import { useState, useRef, useEffect } from "react";

interface HeaderProps {
  auth: AuthContext | null;
  onLogout: () => void;
}

const ROUTE_LABELS: Record<string, string> = {
  "/": "Dashboard",
  "/tickets": "Tickets",
  "/runs": "Runs",
  "/runs/stats": "Run Statistics",
  "/audit/logs": "Audit Logs",
  "/audit/tool-calls": "Tool Calls",
  "/settings/keys": "API Keys",
};

export function Header({ auth, onLogout }: HeaderProps) {
  const location = useLocation();
  const [dropdownOpen, setDropdownOpen] = useState(false);
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

  const pathSegments = location.pathname.split("/").filter(Boolean);
  const currentLabel =
    ROUTE_LABELS[location.pathname] ??
    (pathSegments.length > 0 ? pathSegments[pathSegments.length - 1] : "Dashboard");

  return (
    <header className="fixed top-0 left-0 right-0 h-16 bg-sidebar border-b border-border z-50 flex items-center justify-between px-6">
      <div className="flex items-center gap-4">
        <Link to="/" className="flex items-center gap-2">
          <Shield className="text-accent" size={24} />
          <span className="text-lg font-semibold text-text-primary tracking-tight">SupportAI</span>
        </Link>
        <span className="text-text-muted">/</span>
        <span className="text-sm text-text-secondary">{currentLabel}</span>
      </div>

      {auth && (
        <div className="flex items-center gap-3">
          <span className="text-xs px-2 py-1 rounded border bg-elevated border-border text-text-secondary font-mono">
            {auth.customer_id}
          </span>
          <span
            className={cn(
              "text-xs px-2 py-1 rounded border font-medium",
              ROLE_COLORS[auth.role] ?? "bg-elevated border-border text-text-secondary",
            )}
          >
            {auth.role}
          </span>

          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="flex items-center gap-1 text-text-secondary hover:text-text-primary transition-colors p-1 rounded hover:bg-elevated"
            >
              <ChevronDown size={16} />
            </button>
            {dropdownOpen && (
              <div className="absolute right-0 top-full mt-1 w-48 bg-card border border-border rounded-md shadow-lg py-1 z-50">
                <div className="px-3 py-2 border-b border-border">
                  <p className="text-xs text-text-muted">Key ID</p>
                  <p className="text-xs font-mono text-text-secondary truncate">{auth.key_id}</p>
                </div>
                <button
                  onClick={() => {
                    setDropdownOpen(false);
                    onLogout();
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:text-severity-critical hover:bg-elevated transition-colors"
                >
                  <LogOut size={14} />
                  Disconnect
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
