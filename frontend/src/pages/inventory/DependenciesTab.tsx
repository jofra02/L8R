import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { deleteDependency } from "@/api/endpoints";
import { StatusBadge } from "@/components/common/StatusBadge";
import { EmptyState } from "@/components/common/EmptyState";
import { DependencyModal } from "./DependencyModal";
import type { InventoryDependency, InventoryComponent } from "@/api/types";

export function DependenciesTab({
  dependencies,
  components,
  canWrite,
}: {
  dependencies: InventoryDependency[];
  components: InventoryComponent[];
  canWrite: boolean;
}) {
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);

  const refMap = new Map(components.map((c) => [c.id, c.ref]));

  const deleteMut = useMutation({
    mutationFn: (dep: InventoryDependency) => deleteDependency(dep.source_id, dep.target_id, dep.relation),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Dependency deleted");
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to delete"),
  });

  return (
    <div className="space-y-3">
      {canWrite && (
        <div className="flex justify-end">
          <button
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors"
          >
            <Plus size={16} /> Add Dependency
          </button>
        </div>
      )}

      {dependencies.length === 0 ? (
        <EmptyState message="No dependencies defined" />
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Source</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Target</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Relation</th>
                {canWrite && <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {dependencies.map((d, i) => (
                <tr key={`${d.source_id}-${d.target_id}-${d.relation}-${i}`} className="border-b border-border-subtle hover:bg-elevated/50 transition-colors">
                  <td className="px-4 py-3 text-text-primary">{refMap.get(d.source_id) || d.source_id}</td>
                  <td className="px-4 py-3 text-text-primary">{refMap.get(d.target_id) || d.target_id}</td>
                  <td className="px-4 py-3"><StatusBadge value={d.relation} type="status" /></td>
                  {canWrite && (
                    <td className="px-4 py-3">
                      <button
                        onClick={() => {
                          if (confirm("Delete this dependency?")) deleteMut.mutate(d);
                        }}
                        disabled={deleteMut.isPending}
                        className="p-1.5 text-text-muted hover:text-severity-critical transition-colors"
                        title="Delete"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalOpen && <DependencyModal onClose={() => setModalOpen(false)} components={components} />}
    </div>
  );
}
