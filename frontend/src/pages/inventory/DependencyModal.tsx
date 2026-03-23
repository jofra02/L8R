import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { createDependency } from "@/api/endpoints";
import type { InventoryComponent } from "@/api/types";

const RELATIONS = ["routes_to", "depends_on", "serves", "hosts", "connects_to"];

export function DependencyModal({
  onClose,
  components,
}: {
  onClose: () => void;
  components: InventoryComponent[];
}) {
  const qc = useQueryClient();
  const [sourceId, setSourceId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [relation, setRelation] = useState("depends_on");

  const createMut = useMutation({
    mutationFn: createDependency,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Dependency created");
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to create dependency"),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    createMut.mutate({ source_id: sourceId, target_id: targetId, relation });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-sm shadow-xl">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">Add Dependency</h2>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div>
            <label className="block text-xs text-text-secondary mb-1">Source</label>
            <select
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              required
            >
              <option value="">Select component</option>
              {components.map((c) => (
                <option key={c.id} value={c.id}>{c.ref} ({c.id})</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Target</label>
            <select
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              required
            >
              <option value="">Select component</option>
              {components.map((c) => (
                <option key={c.id} value={c.id}>{c.ref} ({c.id})</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Relation</label>
            <select
              value={relation}
              onChange={(e) => setRelation(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
            >
              {RELATIONS.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
              Cancel
            </button>
            <button
              type="submit"
              disabled={createMut.isPending || !sourceId || !targetId}
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
