import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { deleteBaseline } from "@/api/endpoints";
import { EmptyState } from "@/components/common/EmptyState";
import { BaselineModal } from "./BaselineModal";
import type { InventoryBaseline, InventoryComponent } from "@/api/types";

export function BaselinesTab({
  baselines,
  components,
  canWrite,
}: {
  baselines: InventoryBaseline[];
  components: InventoryComponent[];
  canWrite: boolean;
}) {
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<InventoryBaseline | null>(null);

  const refMap = new Map(components.map((c) => [c.id, c.ref]));

  const deleteMut = useMutation({
    mutationFn: (b: InventoryBaseline) => deleteBaseline(b.component_id, b.metric),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Baseline deleted");
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
            <Plus size={16} /> Add Baseline
          </button>
        </div>
      )}

      {baselines.length === 0 ? (
        <EmptyState message="No baselines defined" />
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Component</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Metric</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Normal Value</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Description</th>
                {canWrite && <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {baselines.map((b) => (
                <tr key={`${b.component_id}-${b.metric}`} className="border-b border-border-subtle hover:bg-elevated/50 transition-colors">
                  <td className="px-4 py-3 text-text-primary">{refMap.get(b.component_id) || b.component_id}</td>
                  <td className="px-4 py-3 font-mono text-xs text-text-primary">{b.metric}</td>
                  <td className="px-4 py-3 text-text-primary">{b.normal_value}</td>
                  <td className="px-4 py-3 text-text-secondary">{b.description || "—"}</td>
                  {canWrite && (
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => { setEditing(b); setModalOpen(true); }}
                          className="p-1.5 text-text-muted hover:text-accent transition-colors"
                          title="Edit"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={() => {
                            if (confirm("Delete this baseline?")) deleteMut.mutate(b);
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

      {modalOpen && <BaselineModal onClose={() => setModalOpen(false)} components={components} editing={editing} />}
    </div>
  );
}
