import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { X, ArrowLeft, Search, Building2 } from "lucide-react";
import { listTenants } from "@/api/endpoints";
import { useAuth } from "@/hooks/useAuth";

interface TenantSwitcherModalProps {
  open: boolean;
  onClose: () => void;
  currentTenantId: string;
}

export function TenantSwitcherModal({ open, onClose, currentTenantId }: TenantSwitcherModalProps) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [filter, setFilter] = useState("");

  const { data: allTenants } = useQuery({
    queryKey: ["tenants"],
    queryFn: listTenants,
    enabled: open && !!user?.is_platform_admin,
  });

  if (!open || !user) return null;

  const isPlatformAdmin = user.is_platform_admin;
  const showBackToGlobal = isPlatformAdmin || user.available_tenants.length > 1;

  // Build tenant list
  let tenantItems: { id: string; name?: string }[];
  if (isPlatformAdmin && allTenants) {
    tenantItems = allTenants.map((t) => ({ id: t.customer_id, name: t.name }));
  } else {
    tenantItems = user.available_tenants.map((id) => ({ id }));
  }

  // Filter out current tenant and apply search
  const filtered = tenantItems
    .filter((t) => t.id !== currentTenantId)
    .filter((t) => {
      if (!filter) return true;
      const q = filter.toLowerCase();
      return t.id.toLowerCase().includes(q) || (t.name?.toLowerCase().includes(q) ?? false);
    });

  const handleSelect = (tenantId: string) => {
    onClose();
    navigate(`/t/${tenantId}`);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-card border border-border rounded-lg w-full max-w-md shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Building2 size={16} className="text-text-secondary" />
            <h2 className="text-sm font-semibold text-text-primary">Switch Tenant</h2>
          </div>
          <button onClick={onClose} className="text-text-secondary hover:text-text-primary transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="p-4 space-y-3">
          {/* Current tenant */}
          <div className="flex items-center gap-2 px-3 py-2 bg-accent/10 border border-accent/20 rounded-md">
            <span className="text-xs text-text-muted">Current:</span>
            <span className="text-sm font-mono text-text-primary">{currentTenantId}</span>
          </div>

          {/* Back to Global */}
          {showBackToGlobal && (
            <button
              onClick={() => { onClose(); navigate("/global"); }}
              className="flex items-center gap-2 w-full px-3 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-elevated rounded-md transition-colors"
            >
              <ArrowLeft size={14} /> Back to Global
            </button>
          )}

          {/* Search */}
          {tenantItems.length > 5 && (
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
              <input
                type="text"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Search tenants..."
                className="w-full bg-elevated border border-border rounded-md pl-9 pr-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
                autoFocus
              />
            </div>
          )}

          {/* Tenant list */}
          <div className="max-h-64 overflow-y-auto space-y-1">
            {filtered.length === 0 ? (
              <p className="text-sm text-text-muted text-center py-4">No other tenants available</p>
            ) : (
              filtered.map((t) => (
                <button
                  key={t.id}
                  onClick={() => handleSelect(t.id)}
                  className="flex items-center justify-between w-full px-3 py-2.5 text-left hover:bg-elevated rounded-md transition-colors group"
                >
                  <div>
                    {t.name && <span className="text-sm text-text-primary block">{t.name}</span>}
                    <span className="text-xs font-mono text-text-secondary">{t.id}</span>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
