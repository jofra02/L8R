import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { deleteComponent } from "@/api/endpoints";
import { StatusBadge } from "@/components/common/StatusBadge";
import { EmptyState } from "@/components/common/EmptyState";
import { ComponentModal } from "./ComponentModal";
import type { InventoryComponent } from "@/api/types";

function McpBadge({ component }: { component: InventoryComponent }) {
  const mcp = component.metadata?.mcp;
  if (!mcp?.managed) return <span className="text-text-secondary">—</span>;
  const status = mcp.sync?.status;
  if (status === "synced") {
    return (
      <span
        className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-severity-low/15 text-severity-low"
        title={mcp.sync?.last_synced_at ? `Last synced: ${mcp.sync.last_synced_at}` : "Synced to the MCP gateway"}
      >
        MCP synced
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-severity-critical/15 text-severity-critical"
      title={`${mcp.sync?.last_error || "Sync pending"} — edit and save the component (re-enter the token) to retry.`}
    >
      MCP sync error
    </span>
  );
}

export function ComponentsTab({
  components,
  canWrite,
}: {
  components: InventoryComponent[];
  canWrite: boolean;
}) {
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<InventoryComponent | null>(null);

  const deleteMut = useMutation({
    mutationFn: deleteComponent,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Component deleted");
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to delete"),
  });

  return (
    <div className="space-y-3">
      {canWrite && (
        <div className="flex justify-end">
          <button
            onClick={() => { setEditing(null); setModalOpen(true); }}
            className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors"
          >
            <Plus size={16} /> Add Component
          </button>
        </div>
      )}

      {components.length === 0 ? (
        <EmptyState message="No components in inventory" />
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">ID</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Ref</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Role</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Vendor</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Priority</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">MCP</th>
                {canWrite && <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {components.map((c) => (
                <tr key={c.id} className="border-b border-border-subtle hover:bg-elevated/50 transition-colors">
                  <td className="px-4 py-3 font-mono text-xs text-text-primary">{c.id}</td>
                  <td className="px-4 py-3 text-text-primary">{c.ref}</td>
                  <td className="px-4 py-3"><StatusBadge value={c.role} type="status" /></td>
                  <td className="px-4 py-3 text-text-secondary">{c.vendor || "—"}</td>
                  <td className="px-4 py-3 text-text-secondary">{c.priority}</td>
                  <td className="px-4 py-3"><McpBadge component={c} /></td>
                  {canWrite && (
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => { setEditing(c); setModalOpen(true); }}
                          className="p-1.5 text-text-muted hover:text-accent transition-colors"
                          title="Edit"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={() => {
                            if (confirm("Delete this component? Related dependencies, baselines, and known changes will also be removed.")) {
                              deleteMut.mutate(c.id);
                            }
                          }}
                          disabled={deleteMut.isPending}
                          className="p-1.5 text-text-muted hover:text-severity-critical transition-colors"
                          title="Delete"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalOpen && <ComponentModal onClose={() => setModalOpen(false)} editing={editing} />}
    </div>
  );
}
