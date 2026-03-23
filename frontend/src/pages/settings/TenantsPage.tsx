import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Plus, Pause, Play } from "lucide-react";
import { toast } from "sonner";
import { listTenants, createTenant, suspendTenant, activateTenant } from "@/api/endpoints";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { EmptyState } from "@/components/common/EmptyState";
import { TimeAgo } from "@/components/common/TimeAgo";
import type { TenantListItem, TenantCreate } from "@/api/types";

export function TenantsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [createOpen, setCreateOpen] = useState(false);

  const { data: tenants, isLoading } = useQuery({
    queryKey: ["tenants"],
    queryFn: listTenants,
  });

  const suspendMut = useMutation({
    mutationFn: suspendTenant,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      toast.success("Tenant suspended");
    },
    onError: () => toast.error("Failed to suspend tenant"),
  });

  const activateMut = useMutation({
    mutationFn: activateTenant,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      toast.success("Tenant activated");
    },
    onError: () => toast.error("Failed to activate tenant"),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Tenants</h1>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors"
        >
          <Plus size={16} /> Create Tenant
        </button>
      </div>

      {isLoading ? (
        <LoadingSpinner className="py-16" />
      ) : !tenants?.length ? (
        <EmptyState message="No tenants" />
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">ID</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Name</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Status</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Plan</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Users</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Tickets</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Last Activity</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Created</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Actions</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((t: TenantListItem) => (
                <tr
                  key={t.customer_id}
                  className="border-b border-border-subtle hover:bg-elevated/30 cursor-pointer"
                  onClick={() => navigate(`/settings/tenants/${t.customer_id}`)}
                >
                  <td className="px-4 py-3 text-text-primary font-mono text-xs">{t.customer_id}</td>
                  <td className="px-4 py-3 text-text-primary">{t.name}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-xs px-2 py-0.5 rounded border ${
                        t.status === "active"
                          ? "bg-green-500/15 text-green-400 border-green-500/30"
                          : "bg-amber-500/15 text-amber-400 border-amber-500/30"
                      }`}
                    >
                      {t.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs px-2 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/30">
                      {t.plan}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-text-secondary">{t.user_count}</td>
                  <td className="px-4 py-3 text-text-secondary">{t.ticket_count}</td>
                  <td className="px-4 py-3"><TimeAgo date={t.last_activity} /></td>
                  <td className="px-4 py-3"><TimeAgo date={t.created_at} /></td>
                  <td className="px-4 py-3">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (t.status === "active") {
                          if (confirm(`Suspend tenant "${t.customer_id}"?`)) suspendMut.mutate(t.customer_id);
                        } else {
                          activateMut.mutate(t.customer_id);
                        }
                      }}
                      className="p-1.5 rounded hover:bg-elevated text-text-secondary hover:text-text-primary transition-colors"
                      title={t.status === "active" ? "Suspend" : "Activate"}
                    >
                      {t.status === "active" ? <Pause size={14} /> : <Play size={14} />}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {createOpen && <CreateTenantModal onClose={() => setCreateOpen(false)} />}
    </div>
  );
}

function CreateTenantModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [customerId, setCustomerId] = useState("");
  const [name, setName] = useState("");
  const [plan, setPlan] = useState("standard");

  const createMut = useMutation({
    mutationFn: (body: TenantCreate) => createTenant(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      toast.success("Tenant created");
      onClose();
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(err.response?.data?.detail ?? "Failed to create tenant");
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-sm shadow-xl">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">Create Tenant</h2>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createMut.mutate({ customer_id: customerId, name, plan });
          }}
          className="p-5 space-y-4"
        >
          <div>
            <label className="block text-xs text-text-secondary mb-1">Tenant ID</label>
            <input
              type="text"
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary font-mono focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="my-tenant-id"
              pattern="^[a-zA-Z0-9_-]+$"
              required
              autoFocus
            />
            <p className="text-xs text-text-muted mt-1">Letters, numbers, hyphens, underscores only.</p>
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Plan</label>
            <select
              value={plan}
              onChange={(e) => setPlan(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
            >
              <option value="standard">Standard</option>
              <option value="premium">Premium</option>
              <option value="enterprise">Enterprise</option>
            </select>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
              Cancel
            </button>
            <button
              type="submit"
              disabled={createMut.isPending}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50"
            >
              {createMut.isPending ? "Creating..." : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
