import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { createComponent, updateComponent } from "@/api/endpoints";
import type { InventoryComponent, ComponentCreate, ComponentUpdate, McpConnection } from "@/api/types";

const ROLES = [
  "firewall", "router", "switch", "loadbalancer", "gateway", "access_point",
  "server", "host", "hypervisor", "node", "cluster", "storage", "nas", "san",
  "vm", "container", "pod", "instance", "function",
  "service", "process", "application", "database", "api", "queue",
  "subnet", "network", "endpoint", "user", "dns_name", "url",
  "appliance", "controller", "unknown",
];

// Appliance packs available in the MCP gateway (extend as packs are added)
const MCP_PACKS = [
  { label: "Fortinet / FortiGate", vendor: "fortinet", appliance: "fortigate", device_type: "fortios" },
];

const inputClass =
  "w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent";

function reportGatewaySync(saved: InventoryComponent, successMsg: string) {
  const sync = saved.gateway_sync;
  if (sync?.status === "error") {
    toast.warning(`Saved locally, but gateway sync failed: ${sync.error ?? "unknown error"}`);
  } else if (sync?.status === "skipped") {
    toast.warning("Saved locally; gateway sync is not configured on the server.");
  } else {
    for (const w of sync?.warnings ?? []) toast.warning(w);
    toast.success(successMsg);
  }
}

export function ComponentModal({
  onClose,
  editing,
}: {
  onClose: () => void;
  editing?: InventoryComponent | null;
}) {
  const qc = useQueryClient();
  const isEdit = !!editing;
  const existingMcp = editing?.metadata?.mcp;

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

  // MCP managed-device section
  const [mcpEnabled, setMcpEnabled] = useState(!!existingMcp?.managed);
  const [mcpPack, setMcpPack] = useState(() => {
    const idx = MCP_PACKS.findIndex((p) => p.device_type === existingMcp?.device_type);
    return idx >= 0 ? idx : 0;
  });
  const [mcpHost, setMcpHost] = useState(existingMcp?.host ?? "");
  const [mcpPort, setMcpPort] = useState(existingMcp?.port ?? 443);
  const [mcpToken, setMcpToken] = useState("");
  const [mcpVerifySsl, setMcpVerifySsl] = useState(!!existingMcp?.verify_ssl);
  const [mcpPrimary, setMcpPrimary] = useState(!!existingMcp?.primary);

  const createMut = useMutation({
    mutationFn: (data: ComponentCreate) => createComponent(data),
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      reportGatewaySync(saved, "Component created");
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to create component"),
  });

  const updateMut = useMutation({
    mutationFn: (data: ComponentUpdate) => updateComponent(editing!.id, data),
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      reportGatewaySync(saved, "Component updated");
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to update component"),
  });

  function buildMcpConnection(): McpConnection | undefined {
    if (!mcpEnabled) return undefined;
    const pack = MCP_PACKS[mcpPack] ?? MCP_PACKS[0];
    if (!pack) return undefined;
    return {
      vendor: pack.vendor,
      appliance: pack.appliance,
      device_type: pack.device_type,
      host: mcpHost.trim(),
      port: mcpPort,
      token: mcpToken.trim() || undefined,
      verify_ssl: mcpVerifySsl,
      primary: mcpPrimary,
    };
  }

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
    if (mcpEnabled) {
      if (!mcpHost.trim()) {
        toast.error("Host is required for an MCP managed device");
        return;
      }
      if (!isEdit && !mcpToken.trim()) {
        toast.error("API token is required to register the device in the gateway");
        return;
      }
    }

    if (isEdit) {
      const body: ComponentUpdate = { ref, role, vendor: vendor || undefined, priority, metadata };
      if (mcpEnabled) {
        body.mcp_connection = buildMcpConnection();
      } else if (existingMcp?.managed) {
        body.mcp_managed = false; // toggle turned off: detach from the gateway
      }
      updateMut.mutate(body);
    } else {
      createMut.mutate({
        id, ref, role, vendor: vendor || undefined, priority, metadata,
        mcp_connection: buildMcpConnection(),
      });
    }
  }

  const isPending = createMut.isPending || updateMut.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-md shadow-xl max-h-[90vh] overflow-y-auto">
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
              className={`${inputClass} disabled:opacity-50`}
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
                className={inputClass}
                required
              />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Role</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className={inputClass}
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
                className={inputClass}
                placeholder="Optional"
              />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Priority</label>
              <input
                type="number"
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
                className={inputClass}
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
              className={`${inputClass} font-mono`}
              placeholder='{"key": "value"}'
            />
          </div>

          <div className="border border-border rounded-md">
            <label className="flex items-center gap-2 px-3 py-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={mcpEnabled}
                onChange={(e) => setMcpEnabled(e.target.checked)}
                className="accent-accent"
              />
              <span className="text-xs font-semibold text-text-primary">MCP managed device</span>
              <span className="text-xs text-text-muted">— register in the gateway inventory for live tool execution</span>
            </label>
            {mcpEnabled && (
              <div className="px-3 pb-3 space-y-3 border-t border-border-subtle pt-3">
                <div>
                  <label className="block text-xs text-text-secondary mb-1">Appliance</label>
                  <select
                    value={mcpPack}
                    onChange={(e) => setMcpPack(Number(e.target.value))}
                    className={inputClass}
                  >
                    {MCP_PACKS.map((p, i) => (
                      <option key={p.device_type} value={i}>{p.label}</option>
                    ))}
                  </select>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-text-secondary mb-1">Host</label>
                    <input
                      type="text"
                      value={mcpHost}
                      onChange={(e) => setMcpHost(e.target.value)}
                      className={inputClass}
                      placeholder="10.0.0.1"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-text-secondary mb-1">Port</label>
                    <input
                      type="number"
                      value={mcpPort}
                      onChange={(e) => setMcpPort(Number(e.target.value))}
                      className={inputClass}
                      min={1}
                      max={65535}
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-text-secondary mb-1">API token</label>
                  <input
                    type="password"
                    value={mcpToken}
                    onChange={(e) => setMcpToken(e.target.value)}
                    className={inputClass}
                    placeholder={isEdit && existingMcp?.managed ? "Unchanged" : "Device API token"}
                    autoComplete="new-password"
                  />
                  <p className="text-[11px] text-text-muted mt-1">
                    Encrypted and stored only in the gateway. If a sync fails, re-enter the token and save again.
                  </p>
                </div>
                <div className="flex items-center gap-5">
                  <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={mcpVerifySsl}
                      onChange={(e) => setMcpVerifySsl(e.target.checked)}
                      className="accent-accent"
                    />
                    Verify SSL
                  </label>
                  <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={mcpPrimary}
                      onChange={(e) => setMcpPrimary(e.target.checked)}
                      className="accent-accent"
                    />
                    Primary device
                  </label>
                </div>
              </div>
            )}
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
