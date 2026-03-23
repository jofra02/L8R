import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { deleteKnownChange } from "@/api/endpoints";
import { StatusBadge } from "@/components/common/StatusBadge";
import { EmptyState } from "@/components/common/EmptyState";
import { KnownChangeModal } from "./KnownChangeModal";
import type { InventoryKnownChange, InventoryComponent } from "@/api/types";

export function KnownChangesTab({
  knownChanges,
  components,
  canWrite,
}: {
  knownChanges: InventoryKnownChange[];
  components: InventoryComponent[];
  canWrite: boolean;
}) {
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<InventoryKnownChange | null>(null);

  const refMap = new Map(components.map((c) => [c.id, c.ref]));

  const deleteMut = useMutation({
    mutationFn: deleteKnownChange,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Known change deleted");
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
            <Plus size={16} /> Add Change
          </button>
        </div>
      )}

      {knownChanges.length === 0 ? (
        <EmptyState message="No known changes recorded" />
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Date</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Description</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Component</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Type</th>
                {canWrite && <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {knownChanges.map((kc) => (
                <tr key={kc.index} className="border-b border-border-subtle hover:bg-elevated/50 transition-colors">
                  <td className="px-4 py-3 text-text-primary whitespace-nowrap">{kc.date}</td>
                  <td className="px-4 py-3 text-text-primary max-w-md truncate">{kc.description}</td>
                  <td className="px-4 py-3 text-text-secondary">
                    {kc.component_id ? (refMap.get(kc.component_id) || kc.component_id) : "—"}
                  </td>
                  <td className="px-4 py-3"><StatusBadge value={kc.change_type} type="status" /></td>
                  {canWrite && (
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => { setEditing(kc); setModalOpen(true); }}
                          className="p-1.5 text-text-muted hover:text-accent transition-colors"
                          title="Edit"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={() => {
                            if (confirm("Delete this known change?")) deleteMut.mutate(kc.index);
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

      {modalOpen && <KnownChangeModal onClose={() => setModalOpen(false)} components={components} editing={editing} />}
    </div>
  );
}
