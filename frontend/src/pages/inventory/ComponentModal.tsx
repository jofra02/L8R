import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { createComponent, updateComponent } from "@/api/endpoints";
import type { InventoryComponent, ComponentCreate, ComponentUpdate } from "@/api/types";

const ROLES = [
  "firewall", "router", "switch", "loadbalancer", "gateway", "access_point",
  "server", "host", "hypervisor", "node", "cluster", "storage", "nas", "san",
  "vm", "container", "pod", "instance", "function",
  "service", "process", "application", "database", "api", "queue",
  "subnet", "network", "endpoint", "user", "dns_name", "url",
  "appliance", "controller", "unknown",
];

export function ComponentModal({
  onClose,
  editing,
}: {
  onClose: () => void;
  editing?: InventoryComponent | null;
}) {
  const qc = useQueryClient();
  const isEdit = !!editing;

  const [id, setId] = useState(editing?.id ?? "");
  const [ref, setRef] = useState(editing?.ref ?? "");
  const [role, setRole] = useState(editing?.role ?? "server");
  const [vendor, setVendor] = useState(editing?.vendor ?? "");
  const [priority, setPriority] = useState(editing?.priority ?? 1);
  const [metaStr, setMetaStr] = useState(
    editing?.metadata && Object.keys(editing.metadata).length > 0
      ? JSON.stringify(editing.metadata, null, 2)
      : ""
  );

  const createMut = useMutation({
    mutationFn: (data: ComponentCreate) => createComponent(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Component created");
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to create component"),
  });

  const updateMut = useMutation({
    mutationFn: (data: ComponentUpdate) => updateComponent(editing!.id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Component updated");
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to update component"),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    let metadata: Record<string, unknown> = {};
    if (metaStr.trim()) {
      try {
        metadata = JSON.parse(metaStr);
      } catch {
        toast.error("Invalid JSON in metadata");
        return;
      }
    }
    if (isEdit) {
      updateMut.mutate({ ref, role, vendor: vendor || undefined, priority, metadata });
    } else {
      createMut.mutate({ id, ref, role, vendor: vendor || undefined, priority, metadata });
    }
  }

  const isPending = createMut.isPending || updateMut.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-md shadow-xl">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">{isEdit ? "Edit Component" : "Add Component"}</h2>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div>
            <label className="block text-xs text-text-secondary mb-1">ID</label>
            <input
              type="text"
              value={id}
              onChange={(e) => setId(e.target.value)}
              disabled={isEdit}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
              required
              autoFocus={!isEdit}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-text-secondary mb-1">Ref</label>
              <input
                type="text"
                value={ref}
                onChange={(e) => setRef(e.target.value)}
                className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
                required
              />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Role</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-text-secondary mb-1">Vendor</label>
              <input
                type="text"
                value={vendor}
                onChange={(e) => setVendor(e.target.value)}
                className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
                placeholder="Optional"
              />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Priority</label>
              <input
                type="number"
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
                className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
                min={1}
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Metadata (JSON)</label>
            <textarea
              value={metaStr}
              onChange={(e) => setMetaStr(e.target.value)}
              rows={3}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary font-mono focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder='{"key": "value"}'
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending || !id.trim() || !ref.trim()}
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
