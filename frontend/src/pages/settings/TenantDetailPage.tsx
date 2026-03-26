import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Pause, Play, Trash2, Plus, Pencil, X, Save, Users, Ticket, Clock } from "lucide-react";
import { toast } from "sonner";
import {
  getTenantDetail,
  updateTenant,
  suspendTenant,
  activateTenant,
  deleteTenant,
  getCascadeWarning,
  upsertTenantEndpoints,
  createTenantScope,
  updateTenantScope,
  deleteTenantScope,
} from "@/api/endpoints";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { TimeAgo } from "@/components/common/TimeAgo";
import type { TenantUpdate, EndpointUpsert, ScopeCreate, ScopeUpdate, TenantScopeResponse } from "@/api/types";

export function TenantDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data: tenant, isLoading } = useQuery({
    queryKey: ["tenants", id],
    queryFn: () => getTenantDetail(id!),
    enabled: !!id,
  });

  if (isLoading) return <LoadingSpinner className="py-16" />;
  if (!tenant) return <div className="py-16 text-center text-text-muted">Tenant not found</div>;

  return (
    <div className="space-y-6">
      <button onClick={() => navigate("/global/tenants")} className="flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary transition-colors">
        <ArrowLeft size={16} /> Back to tenants
      </button>

      <TenantHeader tenant={tenant} />
      <StatsRow tenant={tenant} />
      <InfoCard tenant={tenant} />
      <EndpointsCard customerId={tenant.customer_id} endpoints={tenant.endpoints} />
      <ScopesSection customerId={tenant.customer_id} scopes={tenant.scopes} />
      <DangerZone customerId={tenant.customer_id} />
    </div>
  );
}

// --- Header ---
function TenantHeader({ tenant }: { tenant: { customer_id: string; name: string; status: string } }) {
  const qc = useQueryClient();

  const suspendMut = useMutation({
    mutationFn: () => suspendTenant(tenant.customer_id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      toast.success("Tenant suspended");
    },
    onError: () => toast.error("Failed to suspend"),
  });

  const activateMut = useMutation({
    mutationFn: () => activateTenant(tenant.customer_id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      toast.success("Tenant activated");
    },
    onError: () => toast.error("Failed to activate"),
  });

  const isActive = tenant.status === "active";

  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-text-primary">{tenant.name}</h1>
        <span className="font-mono text-xs text-text-muted">{tenant.customer_id}</span>
        <span
          className={`text-xs px-2 py-0.5 rounded border ${
            isActive
              ? "bg-green-500/15 text-green-400 border-green-500/30"
              : "bg-amber-500/15 text-amber-400 border-amber-500/30"
          }`}
        >
          {tenant.status}
        </span>
      </div>
      <button
        onClick={() => {
          if (isActive) {
            if (confirm(`Suspend tenant "${tenant.customer_id}"?`)) suspendMut.mutate();
          } else {
            activateMut.mutate();
          }
        }}
        className={`flex items-center gap-2 text-sm px-4 py-2 rounded-md transition-colors ${
          isActive
            ? "bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 border border-amber-500/30"
            : "bg-green-500/15 text-green-400 hover:bg-green-500/25 border border-green-500/30"
        }`}
      >
        {isActive ? <><Pause size={14} /> Suspend</> : <><Play size={14} /> Activate</>}
      </button>
    </div>
  );
}

// --- Stats ---
function StatsRow({ tenant }: { tenant: { user_count: number; ticket_count: number; last_activity: string | null } }) {
  const stats = [
    { label: "Users", value: tenant.user_count, icon: <Users size={16} /> },
    { label: "Tickets", value: tenant.ticket_count, icon: <Ticket size={16} /> },
    { label: "Last Activity", value: tenant.last_activity ? <TimeAgo date={tenant.last_activity} /> : "Never", icon: <Clock size={16} /> },
  ];

  return (
    <div className="grid grid-cols-3 gap-4">
      {stats.map((s) => (
        <div key={s.label} className="bg-card border border-border rounded-lg p-4">
          <div className="flex items-center gap-2 text-text-secondary text-xs mb-1">
            {s.icon} {s.label}
          </div>
          <div className="text-lg font-semibold text-text-primary">{s.value}</div>
        </div>
      ))}
    </div>
  );
}

// --- Info Card ---
function InfoCard({ tenant }: { tenant: { customer_id: string; name: string; plan: string } }) {
  const qc = useQueryClient();
  const [name, setName] = useState(tenant.name);
  const [plan, setPlan] = useState(tenant.plan);
  const dirty = name !== tenant.name || plan !== tenant.plan;

  const updateMut = useMutation({
    mutationFn: (body: TenantUpdate) => updateTenant(tenant.customer_id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      toast.success("Tenant updated");
    },
    onError: () => toast.error("Failed to update"),
  });

  return (
    <div className="bg-card border border-border rounded-lg p-5 space-y-4">
      <h2 className="text-sm font-semibold text-text-primary">Tenant Info</h2>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-text-secondary mb-1">Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
          />
        </div>
        <div>
          <label className="block text-xs text-text-secondary mb-1">Plan</label>
          <select
            value={plan}
            onChange={(e) => setPlan(e.target.value)}
            className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
          >
            <option value="standard">Standard</option>
            <option value="premium">Premium</option>
            <option value="enterprise">Enterprise</option>
          </select>
        </div>
      </div>
      {dirty && (
        <div className="flex justify-end">
          <button
            onClick={() => updateMut.mutate({ name, plan })}
            disabled={updateMut.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50"
          >
            <Save size={14} /> {updateMut.isPending ? "Saving..." : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}

// --- Endpoints ---
function EndpointsCard({
  customerId,
  endpoints,
}: {
  customerId: string;
  endpoints: { pg_dsn_ref: string | null; qdrant_url_ref: string | null; object_store_ref: string | null } | null;
}) {
  const qc = useQueryClient();
  const [pgDsn, setPgDsn] = useState(endpoints?.pg_dsn_ref ?? "");
  const [qdrantUrl, setQdrantUrl] = useState(endpoints?.qdrant_url_ref ?? "");
  const [objectStore, setObjectStore] = useState(endpoints?.object_store_ref ?? "");

  const upsertMut = useMutation({
    mutationFn: (body: EndpointUpsert) => upsertTenantEndpoints(customerId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants", customerId] });
      toast.success("Endpoints saved");
    },
    onError: () => toast.error("Failed to save endpoints"),
  });

  const fields = [
    { label: "PostgreSQL DSN Reference", value: pgDsn, onChange: setPgDsn, placeholder: "vault:secret/pg-dsn or env:PG_DSN" },
    { label: "Qdrant URL Reference", value: qdrantUrl, onChange: setQdrantUrl, placeholder: "vault:secret/qdrant-url or env:QDRANT_URL" },
    { label: "Object Store Reference", value: objectStore, onChange: setObjectStore, placeholder: "vault:secret/s3-bucket or env:OBJECT_STORE" },
  ];

  return (
    <div className="bg-card border border-border rounded-lg p-5 space-y-4">
      <h2 className="text-sm font-semibold text-text-primary">Infrastructure Endpoints</h2>
      <div className="space-y-3">
        {fields.map((f) => (
          <div key={f.label}>
            <label className="block text-xs text-text-secondary mb-1">{f.label}</label>
            <input
              type="text"
              value={f.value}
              onChange={(e) => f.onChange(e.target.value)}
              placeholder={f.placeholder}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary font-mono focus:outline-none focus:ring-2 focus:ring-accent"
            />
          </div>
        ))}
      </div>
      <div className="flex justify-end">
        <button
          onClick={() =>
            upsertMut.mutate({
              pg_dsn_ref: pgDsn || null,
              qdrant_url_ref: qdrantUrl || null,
              object_store_ref: objectStore || null,
            })
          }
          disabled={upsertMut.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50"
        >
          <Save size={14} /> {upsertMut.isPending ? "Saving..." : "Save Endpoints"}
        </button>
      </div>
    </div>
  );
}

// --- Scopes ---
function ScopesSection({ customerId, scopes }: { customerId: string; scopes: TenantScopeResponse[] }) {
  const qc = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [editScope, setEditScope] = useState<TenantScopeResponse | null>(null);

  const deleteMut = useMutation({
    mutationFn: (scopeId: number) => deleteTenantScope(customerId, scopeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants", customerId] });
      toast.success("Scope deleted");
    },
    onError: () => toast.error("Failed to delete scope"),
  });

  return (
    <div className="bg-card border border-border rounded-lg p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-text-primary">Capability Scopes</h2>
        <button
          onClick={() => setAddOpen(true)}
          className="flex items-center gap-1 text-xs text-accent hover:text-accent-hover transition-colors"
        >
          <Plus size={14} /> Add Scope
        </button>
      </div>

      {scopes.length === 0 ? (
        <p className="text-sm text-text-muted py-4 text-center">No scopes configured</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left px-3 py-2 text-xs font-semibold text-text-secondary">Scope</th>
              <th className="text-left px-3 py-2 text-xs font-semibold text-text-secondary">Allowed Tools</th>
              <th className="text-left px-3 py-2 text-xs font-semibold text-text-secondary">Rate Limit</th>
              <th className="text-left px-3 py-2 text-xs font-semibold text-text-secondary">Created</th>
              <th className="text-right px-3 py-2 text-xs font-semibold text-text-secondary">Actions</th>
            </tr>
          </thead>
          <tbody>
            {scopes.map((s) => (
              <tr key={s.id} className="border-b border-border-subtle">
                <td className="px-3 py-2 text-text-primary font-mono text-xs">{s.scope_name}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {s.allowed_tools.map((t) => (
                      <span key={t} className="text-xs px-1.5 py-0.5 rounded bg-elevated text-text-secondary border border-border">
                        {t}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2 text-text-secondary">{s.rate_limit ?? "-"}</td>
                <td className="px-3 py-2"><TimeAgo date={s.created_at} /></td>
                <td className="px-3 py-2 text-right space-x-1">
                  <button
                    onClick={() => setEditScope(s)}
                    className="p-1 rounded hover:bg-elevated text-text-secondary hover:text-text-primary transition-colors"
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    onClick={() => { if (confirm(`Delete scope "${s.scope_name}"?`)) deleteMut.mutate(s.id); }}
                    className="p-1 rounded hover:bg-elevated text-text-secondary hover:text-red-400 transition-colors"
                  >
                    <Trash2 size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {addOpen && <ScopeModal customerId={customerId} onClose={() => setAddOpen(false)} />}
      {editScope && <ScopeModal customerId={customerId} scope={editScope} onClose={() => setEditScope(null)} />}
    </div>
  );
}

function ScopeModal({
  customerId,
  scope,
  onClose,
}: {
  customerId: string;
  scope?: TenantScopeResponse;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const isEdit = !!scope;
  const [scopeName, setScopeName] = useState(scope?.scope_name ?? "");
  const [toolsText, setToolsText] = useState(scope?.allowed_tools.join("\n") ?? "");
  const [rateLimit, setRateLimit] = useState(scope?.rate_limit?.toString() ?? "");

  const createMut = useMutation({
    mutationFn: (body: ScopeCreate) => createTenantScope(customerId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants", customerId] });
      toast.success("Scope created");
      onClose();
    },
    onError: (err: { response?: { data?: { detail?: string } } }) =>
      toast.error(err.response?.data?.detail ?? "Failed to create scope"),
  });

  const updateMut = useMutation({
    mutationFn: (body: ScopeUpdate) => updateTenantScope(customerId, scope!.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants", customerId] });
      toast.success("Scope updated");
      onClose();
    },
    onError: () => toast.error("Failed to update scope"),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const tools = toolsText
      .split("\n")
      .map((t) => t.trim())
      .filter(Boolean);
    const rl = rateLimit ? parseInt(rateLimit, 10) : null;

    if (isEdit) {
      updateMut.mutate({ scope_name: scopeName, allowed_tools: tools, rate_limit: rl });
    } else {
      createMut.mutate({ scope_name: scopeName, allowed_tools: tools, rate_limit: rl });
    }
  };

  const isPending = createMut.isPending || updateMut.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-sm shadow-xl">
        <div className="px-5 py-4 border-b border-border flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary">{isEdit ? "Edit Scope" : "Add Scope"}</h2>
          <button onClick={onClose} className="text-text-secondary hover:text-text-primary"><X size={16} /></button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div>
            <label className="block text-xs text-text-secondary mb-1">Scope Name</label>
            <input
              type="text"
              value={scopeName}
              onChange={(e) => setScopeName(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary font-mono focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="network_read"
              required
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Allowed Tools (one per line)</label>
            <textarea
              value={toolsText}
              onChange={(e) => setToolsText(e.target.value)}
              rows={4}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary font-mono focus:outline-none focus:ring-2 focus:ring-accent resize-none"
              placeholder={"ping\ndns*\ntraceroute"}
            />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Rate Limit (requests/min, optional)</label>
            <input
              type="number"
              value={rateLimit}
              onChange={(e) => setRateLimit(e.target.value)}
              min={1}
              className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="Leave blank for unlimited"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">Cancel</button>
            <button type="submit" disabled={isPending}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50">
              {isPending ? "Saving..." : isEdit ? "Update" : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// --- Danger Zone ---
function DangerZone({ customerId }: { customerId: string }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  const warningQuery = useQuery({
    queryKey: ["tenants", customerId, "cascade"],
    queryFn: () => getCascadeWarning(customerId),
    enabled: confirmOpen,
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteTenant(customerId, true),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      toast.success("Tenant deleted");
      navigate("/global/tenants");
    },
    onError: () => toast.error("Failed to delete tenant"),
  });

  return (
    <div className="bg-card border border-red-500/30 rounded-lg p-5 space-y-4">
      <h2 className="text-sm font-semibold text-red-400">Danger Zone</h2>
      <p className="text-sm text-text-secondary">
        Permanently delete this tenant and all associated data (tickets, runs, audit logs, API keys, user assignments).
      </p>
      <button
        onClick={() => setConfirmOpen(true)}
        className="flex items-center gap-2 text-sm px-4 py-2 rounded-md bg-red-500/15 text-red-400 hover:bg-red-500/25 border border-red-500/30 transition-colors"
      >
        <Trash2 size={14} /> Delete Tenant
      </button>

      {confirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-card border border-border rounded-lg w-full max-w-sm shadow-xl">
            <div className="px-5 py-4 border-b border-border">
              <h2 className="text-sm font-semibold text-red-400">Confirm Deletion</h2>
            </div>
            <div className="p-5 space-y-4">
              {warningQuery.data && (
                <div className="bg-red-500/10 border border-red-500/20 rounded-md p-3 text-xs text-red-300 space-y-1">
                  <p>{warningQuery.data.message}</p>
                  <p>Users: {warningQuery.data.user_count} | Tickets: {warningQuery.data.ticket_count} | API Keys: {warningQuery.data.api_key_count}</p>
                </div>
              )}
              <p className="text-sm text-text-secondary">
                Type <span className="font-mono text-text-primary">{customerId}</span> to confirm:
              </p>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary font-mono focus:outline-none focus:ring-2 focus:ring-red-500"
                autoFocus
              />
              <div className="flex justify-end gap-3 pt-2">
                <button
                  onClick={() => { setConfirmOpen(false); setConfirmText(""); }}
                  className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary"
                >
                  Cancel
                </button>
                <button
                  onClick={() => deleteMut.mutate()}
                  disabled={confirmText !== customerId || deleteMut.isPending}
                  className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm rounded-md transition-colors disabled:opacity-50"
                >
                  {deleteMut.isPending ? "Deleting..." : "Delete Forever"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
