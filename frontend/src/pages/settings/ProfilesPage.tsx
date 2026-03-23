import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { listProfiles, listPermissions, createProfile, deleteProfile } from "@/api/endpoints";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { EmptyState } from "@/components/common/EmptyState";
import type { ProfileResponse, PermissionResponse } from "@/api/types";

export function ProfilesPage() {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);

  const { data: profiles, isLoading } = useQuery({
    queryKey: ["profiles"],
    queryFn: listProfiles,
  });

  const deleteMut = useMutation({
    mutationFn: deleteProfile,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profiles"] });
      toast.success("Profile deleted");
    },
    onError: (err: { response?: { data?: { message?: string } } }) => {
      toast.error(err.response?.data?.message ?? "Cannot delete profile");
    },
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Profiles</h1>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors"
        >
          <Plus size={16} /> Create Profile
        </button>
      </div>

      {isLoading ? (
        <LoadingSpinner className="py-16" />
      ) : !profiles?.length ? (
        <EmptyState message="No profiles" />
      ) : (
        <div className="space-y-3">
          {profiles.map((p: ProfileResponse) => (
            <div key={p.id} className="bg-card border border-border rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-medium text-text-primary">{p.name}</h3>
                  {p.is_system && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent/15 text-accent border border-accent/30">system</span>
                  )}
                </div>
                {!p.is_system && (
                  <button
                    onClick={() => {
                      if (confirm(`Delete profile "${p.name}"?`)) deleteMut.mutate(p.id);
                    }}
                    className="p-1.5 text-text-muted hover:text-severity-critical transition-colors"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
              <p className="text-xs text-text-secondary mb-2">{p.description}</p>
              <div className="flex flex-wrap gap-1">
                {p.permissions.map((perm) => (
                  <span key={perm.id} className="text-[10px] px-1.5 py-0.5 rounded bg-elevated border border-border text-text-secondary font-mono">
                    {perm.id}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {createOpen && <CreateProfileModal onClose={() => setCreateOpen(false)} />}
    </div>
  );
}

function CreateProfileModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedPerms, setSelectedPerms] = useState<Set<string>>(new Set());

  const { data: permissions } = useQuery({
    queryKey: ["permissions"],
    queryFn: listPermissions,
  });

  const createMut = useMutation({
    mutationFn: () => createProfile({ name, description, permission_ids: Array.from(selectedPerms) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profiles"] });
      toast.success("Profile created");
      onClose();
    },
    onError: (err: { response?: { data?: { message?: string } } }) => {
      toast.error(err.response?.data?.message ?? "Failed to create profile");
    },
  });

  function togglePerm(id: string) {
    setSelectedPerms((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Group permissions by resource
  const grouped = (permissions ?? []).reduce<Record<string, PermissionResponse[]>>((acc, p) => {
    (acc[p.resource] ??= []).push(p);
    return acc;
  }, {});

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-md shadow-xl max-h-[80vh] flex flex-col">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">Create Profile</h2>
        </div>
        <form
          onSubmit={(e) => { e.preventDefault(); createMut.mutate(); }}
          className="p-5 space-y-4 overflow-y-auto flex-1"
        >
          <div>
            <label className="block text-xs text-text-secondary mb-1">Name</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              required autoFocus />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Description</label>
            <input type="text" value={description} onChange={(e) => setDescription(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent" />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-2">Permissions</label>
            <div className="space-y-3">
              {Object.entries(grouped).map(([resource, perms]) => (
                <div key={resource}>
                  <p className="text-xs font-medium text-text-muted uppercase mb-1">{resource}</p>
                  <div className="flex flex-wrap gap-2">
                    {perms.map((p) => (
                      <label key={p.id} className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer">
                        <input
                          type="checkbox"
                          checked={selectedPerms.has(p.id)}
                          onChange={() => togglePerm(p.id)}
                          className="rounded border-border"
                        />
                        {p.action}
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">Cancel</button>
            <button type="submit" disabled={createMut.isPending || !name.trim()}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50">
              {createMut.isPending ? "Creating..." : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
