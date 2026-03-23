import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Pause, Play, Pencil, X } from "lucide-react";
import { toast } from "sonner";
import { listTenants, createTenant, deleteTenant, suspendTenant, activateTenant } from "@/api/endpoints";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { EmptyState } from "@/components/common/EmptyState";
import { TimeAgo } from "@/components/common/TimeAgo";
import type { TenantListItem, TenantCreate } from "@/api/types";

export function TenantManagementPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [bulkLoading, setBulkLoading] = useState(false);

  const selectionMode = selected.size > 0;

  const { data: tenants, isLoading } = useQuery({
    queryKey: ["tenants"],
    queryFn: listTenants,
  });

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (!tenants) return;
    if (selected.size === tenants.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(tenants.map((t) => t.customer_id)));
    }
  };

  const handleBulkSuspend = async () => {
    if (!confirm(`Suspend ${selected.size} tenant(s)?`)) return;
    setBulkLoading(true);
    try {
      await Promise.all(Array.from(selected).map((id) => suspendTenant(id)));
      qc.invalidateQueries({ queryKey: ["tenants"] });
      toast.success(`Suspended ${selected.size} tenant(s)`);
      setSelected(new Set());
    } catch {
      toast.error("Some tenants failed to suspend");
    } finally {
      setBulkLoading(false);
    }
  };

  const handleBulkActivate = async () => {
    setBulkLoading(true);
    try {
      await Promise.all(Array.from(selected).map((id) => activateTenant(id)));
      qc.invalidateQueries({ queryKey: ["tenants"] });
      toast.success(`Activated ${selected.size} tenant(s)`);
      setSelected(new Set());
    } catch {
      toast.error("Some tenants failed to activate");
    } finally {
      setBulkLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Tenant Management</h1>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors"
        >
          <Plus size={16} /> New Tenant
        </button>
      </div>

      {/* Bulk action toolbar */}
      {selectionMode && (
        <div className="flex items-center gap-2 bg-elevated border border-border rounded-lg px-4 py-2.5">
          <span className="text-xs text-text-secondary mr-2">{selected.size} selected</span>
          <button
            onClick={handleBulkSuspend}
            disabled={bulkLoading}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 border border-amber-500/30 transition-colors disabled:opacity-50"
          >
            <Pause size={12} /> Suspend
          </button>
          <button
            onClick={handleBulkActivate}
            disabled={bulkLoading}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-green-500/15 text-green-400 hover:bg-green-500/25 border border-green-500/30 transition-colors disabled:opacity-50"
          >
            <Play size={12} /> Activate
          </button>
          <button
            onClick={() => setDeleteConfirmOpen(true)}
            disabled={bulkLoading}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-red-500/15 text-red-400 hover:bg-red-500/25 border border-red-500/30 transition-colors disabled:opacity-50"
          >
            <Trash2 size={12} /> Delete
          </button>
          <div className="flex-1" />
          <button
            onClick={() => setSelected(new Set())}
            className="flex items-center gap-1 text-xs text-text-muted hover:text-text-primary transition-colors"
          >
            <X size={12} /> Clear
          </button>
        </div>
      )}

      {isLoading ? (
        <LoadingSpinner className="py-16" />
      ) : !tenants?.length ? (
        <EmptyState message="No tenants" />
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 w-10">
                  {selectionMode ? (
                    <input
                      type="checkbox"
                      checked={selected.size === tenants.length && tenants.length > 0}
                      onChange={toggleAll}
                      className="rounded border-border"
                    />
                  ) : (
                    <span className="block w-4" />
                  )}
                </th>
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
                  className="group border-b border-border-subtle hover:bg-elevated/30 cursor-pointer"
                  onClick={() => navigate(`/t/${t.customer_id}`)}
                >
                  <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(t.customer_id)}
                      onChange={() => toggleSelect(t.customer_id)}
                      className={`rounded border-border transition-opacity ${
                        selectionMode ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                      }`}
                    />
                  </td>
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
                  <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => navigate(`/global/tenants/${t.customer_id}`)}
                      className="p-1.5 rounded hover:bg-elevated text-text-secondary hover:text-text-primary transition-colors"
                      title="Edit"
                    >
                      <Pencil size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {createOpen && <CreateTenantModal onClose={() => setCreateOpen(false)} />}
      {deleteConfirmOpen && (
        <BulkDeleteModal
          selectedIds={Array.from(selected)}
          onClose={() => setDeleteConfirmOpen(false)}
          onDone={() => { setSelected(new Set()); setDeleteConfirmOpen(false); }}
        />
      )}
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
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["tenants"] });
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
          onSubmit={(e) => { e.preventDefault(); createMut.mutate({ customer_id: customerId, name, plan }); }}
          className="p-5 space-y-4"
        >
          <div>
            <label className="block text-xs text-text-secondary mb-1">Tenant ID</label>
            <input type="text" value={customerId} onChange={(e) => setCustomerId(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary font-mono focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="my-tenant-id" pattern="^[a-zA-Z0-9_-]+$" required autoFocus />
            <p className="text-xs text-text-muted mt-1">Letters, numbers, hyphens, underscores only.</p>
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Name</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent" required />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Plan</label>
            <select value={plan} onChange={(e) => setPlan(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent">
              <option value="standard">Standard</option>
              <option value="premium">Premium</option>
              <option value="enterprise">Enterprise</option>
            </select>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">Cancel</button>
            <button type="submit" disabled={createMut.isPending}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50">
              {createMut.isPending ? "Creating..." : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function BulkDeleteModal({ selectedIds, onClose, onDone }: { selectedIds: string[]; onClose: () => void; onDone: () => void }) {
  const qc = useQueryClient();
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await Promise.all(selectedIds.map((id) => deleteTenant(id, true)));
      qc.invalidateQueries({ queryKey: ["tenants"] });
      toast.success(`Deleted ${selectedIds.length} tenant(s)`);
      onDone();
    } catch {
      toast.error("Some tenants failed to delete");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-sm shadow-xl">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-red-400">Delete Tenants</h2>
        </div>
        <div className="p-5 space-y-4">
          <p className="text-sm text-text-secondary">
            Delete <strong className="text-text-primary">{selectedIds.length}</strong> tenant(s) and all their associated data? This cannot be undone.
          </p>
          <div className="bg-red-500/10 border border-red-500/20 rounded-md p-3 text-xs text-red-300 font-mono space-y-0.5 max-h-32 overflow-y-auto">
            {selectedIds.map((id) => <div key={id}>{id}</div>)}
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">Cancel</button>
            <button onClick={handleDelete} disabled={deleting}
              className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm rounded-md transition-colors disabled:opacity-50">
              {deleting ? "Deleting..." : "Delete All"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
