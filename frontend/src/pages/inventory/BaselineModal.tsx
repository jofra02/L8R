import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { createBaseline, updateBaseline } from "@/api/endpoints";
import type { InventoryComponent, InventoryBaseline } from "@/api/types";

export function BaselineModal({
  onClose,
  components,
  editing,
}: {
  onClose: () => void;
  components: InventoryComponent[];
  editing?: InventoryBaseline | null;
}) {
  const qc = useQueryClient();
  const isEdit = !!editing;

  const [componentId, setComponentId] = useState(editing?.component_id ?? "");
  const [metric, setMetric] = useState(editing?.metric ?? "");
  const [normalValue, setNormalValue] = useState(editing?.normal_value ?? "");
  const [description, setDescription] = useState(editing?.description ?? "");

  const createMut = useMutation({
    mutationFn: createBaseline,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Baseline created");
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to create baseline"),
  });

  const updateMut = useMutation({
    mutationFn: (body: { normal_value?: string; description?: string }) =>
      updateBaseline(editing!.component_id, editing!.metric, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Baseline updated");
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to update baseline"),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (isEdit) {
      updateMut.mutate({ normal_value: normalValue, description });
    } else {
      createMut.mutate({ component_id: componentId, metric, normal_value: normalValue, description });
    }
  }

  const isPending = createMut.isPending || updateMut.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-sm shadow-xl">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">{isEdit ? "Edit Baseline" : "Add Baseline"}</h2>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div>
            <label className="block text-xs text-text-secondary mb-1">Component</label>
            <select
              value={componentId}
              onChange={(e) => setComponentId(e.target.value)}
              disabled={isEdit}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
              required
            >
              <option value="">Select component</option>
              {components.map((c) => (
                <option key={c.id} value={c.id}>{c.ref} ({c.id})</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Metric</label>
            <input
              type="text"
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              disabled={isEdit}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
              required
              placeholder="e.g. cpu_usage, latency_ms"
            />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Normal Value</label>
            <input
              type="text"
              value={normalValue}
              onChange={(e) => setNormalValue(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              required
              placeholder='e.g. < 60%, ~30ms'
            />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="Optional"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending || !componentId || !metric.trim() || !normalValue.trim()}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50"
            >
              {isPending ? "Saving..." : isEdit ? "Update" : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
