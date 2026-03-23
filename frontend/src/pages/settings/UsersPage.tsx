import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { listUsers, createUser } from "@/api/endpoints";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { EmptyState } from "@/components/common/EmptyState";
import { TimeAgo } from "@/components/common/TimeAgo";
import type { UserCreateRequest, UserResponse } from "@/api/types";

export function UsersPage() {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);

  const { data: users, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: listUsers,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Users</h1>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors"
        >
          <Plus size={16} /> Create User
        </button>
      </div>

      {isLoading ? (
        <LoadingSpinner className="py-16" />
      ) : !users?.length ? (
        <EmptyState message="No users" />
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Email</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Name</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Active</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Admin</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Last Login</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Created</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u: UserResponse) => (
                <tr key={u.id} className="border-b border-border-subtle">
                  <td className="px-4 py-3 text-text-primary font-mono text-xs">{u.email}</td>
                  <td className="px-4 py-3 text-text-primary">{u.display_name}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-block w-2 h-2 rounded-full ${u.is_active ? "bg-status-completed" : "bg-status-failed"}`} />
                  </td>
                  <td className="px-4 py-3">
                    {u.is_platform_admin && (
                      <span className="text-xs px-2 py-0.5 rounded bg-purple-500/15 text-purple-400 border border-purple-500/30">
                        admin
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3"><TimeAgo date={u.last_login_at} /></td>
                  <td className="px-4 py-3"><TimeAgo date={u.created_at} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {createOpen && <CreateUserModal onClose={() => setCreateOpen(false)} />}
    </div>
  );
}

function CreateUserModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);

  const createMut = useMutation({
    mutationFn: (body: UserCreateRequest) => createUser(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success("User created");
      onClose();
    },
    onError: (err: { response?: { data?: { message?: string } } }) => {
      toast.error(err.response?.data?.message ?? "Failed to create user");
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-sm shadow-xl">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">Create User</h2>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createMut.mutate({
              email,
              display_name: displayName,
              password,
              is_platform_admin: isAdmin,
            });
          }}
          className="p-5 space-y-4"
        >
          <div>
            <label className="block text-xs text-text-secondary mb-1">Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              required autoFocus />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Display Name</label>
            <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              required />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              required />
            <p className="text-xs text-text-muted mt-1">Min 12 chars, 1 uppercase, 1 symbol. User will be forced to change on first login.</p>
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="isAdmin" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)}
              className="rounded border-border" />
            <label htmlFor="isAdmin" className="text-sm text-text-secondary">Platform Admin</label>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">Cancel</button>
            <button type="submit" disabled={createMut.isPending}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50">
              {createMut.isPending ? "Creating..." : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
