import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { createKnownChange, updateKnownChange } from "@/api/endpoints";
import type { InventoryComponent, InventoryKnownChange } from "@/api/types";

const CHANGE_TYPES = ["update", "addition", "removal", "config_change"];

export function KnownChangeModal({
  onClose,
  components,
  editing,
}: {
  onClose: () => void;
  components: InventoryComponent[];
  editing?: InventoryKnownChange | null;
}) {
  const qc = useQueryClient();
  const isEdit = !!editing;

  const [date, setDate] = useState(editing?.date ?? "");
  const [description, setDescription] = useState(editing?.description ?? "");
  const [componentId, setComponentId] = useState(editing?.component_id ?? "");
  const [changeType, setChangeType] = useState(editing?.change_type ?? "update");

  const createMut = useMutation({
    mutationFn: createKnownChange,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Known change added");
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to add change"),
  });

  const updateMut = useMutation({
    mutationFn: (body: { date?: string; description?: string; component_id?: string; change_type?: string }) =>
      updateKnownChange(editing!.index, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Known change updated");
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to update change"),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const data = {
      date,
      description,
      component_id: componentId || undefined,
      change_type: changeType,
    };
    if (isEdit) {
      updateMut.mutate(data);
    } else {
      createMut.mutate(data);
    }
  }

  const isPending = createMut.isPending || updateMut.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-sm shadow-xl">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">{isEdit ? "Edit Known Change" : "Add Known Change"}</h2>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-text-secondary mb-1">Date</label>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
                required
              />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Type</label>
              <select
                value={changeType}
                onChange={(e) => setChangeType(e.target.value)}
                className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              >
                {CHANGE_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Component (optional)</label>
            <select
              value={componentId}
              onChange={(e) => setComponentId(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
            >
              <option value="">None</option>
              {components.map((c) => (
                <option key={c.id} value={c.id}>{c.ref} ({c.id})</option>
              ))}
            </select>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending || !date || !description.trim()}
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
