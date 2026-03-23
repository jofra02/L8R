import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, RotateCw, Trash2, Copy, Check } from "lucide-react";
import { toast } from "sonner";
import { listApiKeys, createApiKey, revokeApiKey, rotateApiKey, listProfiles } from "@/api/endpoints";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { EmptyState } from "@/components/common/EmptyState";
import { ROLE_HIERARCHY } from "@/lib/constants";
import type { ApiKeyCreatedResponse } from "@/api/types";

export function ApiKeysPage() {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [newKey, setNewKey] = useState<ApiKeyCreatedResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const { data: keys, isLoading } = useQuery({
    queryKey: ["api-keys"],
    queryFn: listApiKeys,
  });

  const revokeMut = useMutation({
    mutationFn: revokeApiKey,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["api-keys"] });
      toast.success("Key revoked");
    },
    onError: () => toast.error("Failed to revoke key"),
  });

  const rotateMut = useMutation({
    mutationFn: rotateApiKey,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["api-keys"] });
      setNewKey(data);
      toast.success("Key rotated");
    },
    onError: () => toast.error("Failed to rotate key"),
  });

  function copyKey(key: string) {
    navigator.clipboard.writeText(key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">API Keys</h1>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors"
        >
          <Plus size={16} /> Create Key
        </button>
      </div>

      {/* New key banner */}
      {newKey && (
        <div className="bg-status-completed/10 border border-status-completed/30 rounded-lg p-4">
          <p className="text-sm text-text-primary mb-2">New key created. Copy it now - it will not be shown again.</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-elevated px-3 py-2 rounded text-xs font-mono text-text-primary border border-border">
              {newKey.raw_key}
            </code>
            <button
              onClick={() => copyKey(newKey.raw_key)}
              className="p-2 bg-elevated border border-border rounded hover:bg-card transition-colors"
            >
              {copied ? <Check size={14} className="text-status-completed" /> : <Copy size={14} className="text-text-secondary" />}
            </button>
          </div>
          <button onClick={() => setNewKey(null)} className="text-xs text-text-muted mt-2 hover:text-text-secondary">
            Dismiss
          </button>
        </div>
      )}

      {isLoading ? (
        <LoadingSpinner className="py-16" />
      ) : !keys?.length ? (
        <EmptyState message="No API keys" />
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Name</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Prefix</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Role</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Active</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Last Used</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Created</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Actions</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id} className="border-b border-border-subtle">
                  <td className="px-4 py-3 text-text-primary">{k.name}</td>
                  <td className="px-4 py-3 font-mono text-xs text-text-secondary">{k.key_prefix}...</td>
                  <td className="px-4 py-3"><StatusBadge value={k.role} type="role" /></td>
                  <td className="px-4 py-3">
                    <span className={`inline-block w-2 h-2 rounded-full ${k.is_active ? "bg-status-completed" : "bg-status-failed"}`} />
                  </td>
                  <td className="px-4 py-3"><TimeAgo date={k.last_used_at} /></td>
                  <td className="px-4 py-3"><TimeAgo date={k.created_at} /></td>
                  <td className="px-4 py-3">
                    {k.is_active && (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => rotateMut.mutate(k.id)}
                          disabled={rotateMut.isPending}
                          className="p-1.5 text-text-muted hover:text-accent transition-colors"
                          title="Rotate"
                        >
                          <RotateCw size={14} />
                        </button>
                        <button
                          onClick={() => {
                            if (confirm("Revoke this key? This cannot be undone.")) {
                              revokeMut.mutate(k.id);
                            }
                          }}
                          disabled={revokeMut.isPending}
                          className="p-1.5 text-text-muted hover:text-severity-critical transition-colors"
                          title="Revoke"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {createOpen && <CreateKeyModal onClose={() => setCreateOpen(false)} onCreated={setNewKey} />}
    </div>
  );
}

function CreateKeyModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (key: ApiKeyCreatedResponse) => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [role, setRole] = useState("operator");
  const [profileId, setProfileId] = useState("");

  const { data: profiles } = useQuery({
    queryKey: ["profiles"],
    queryFn: listProfiles,
  });

  const createMut = useMutation({
    mutationFn: createApiKey,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["api-keys"] });
      onCreated(data);
      onClose();
    },
    onError: () => toast.error("Failed to create key"),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-sm shadow-xl">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">Create API Key</h2>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return;
            createMut.mutate({
              name: name.trim(),
              role,
              profile_id: profileId || undefined,
            });
          }}
          className="p-5 space-y-4"
        >
          <div>
            <label className="block text-xs text-text-secondary mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              required
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Profile</label>
            <select
              value={profileId}
              onChange={(e) => setProfileId(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
            >
              <option value="">— Use legacy role —</option>
              {profiles?.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <p className="text-xs text-text-muted mt-1">
              {profileId ? "Permissions resolved from selected profile" : "Fallback: permissions mapped from role below"}
            </p>
          </div>
          {!profileId && (
            <div>
              <label className="block text-xs text-text-secondary mb-1">Legacy Role</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              >
                {ROLE_HIERARCHY.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
          )}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
              Cancel
            </button>
            <button
              type="submit"
              disabled={createMut.isPending || !name.trim()}
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
