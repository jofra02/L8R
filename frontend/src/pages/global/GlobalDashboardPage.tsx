import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Building2, Ticket, Users } from "lucide-react";
import { listTenants } from "@/api/endpoints";
import { StatCard } from "@/components/common/StatCard";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { EmptyState } from "@/components/common/EmptyState";
import { TimeAgo } from "@/components/common/TimeAgo";
import type { TenantListItem } from "@/api/types";

export function GlobalDashboardPage() {
  const navigate = useNavigate();
  const { data: tenants, isLoading } = useQuery({
    queryKey: ["tenants"],
    queryFn: listTenants,
  });

  if (isLoading) return <LoadingSpinner className="py-32" />;

  const totalTenants = tenants?.length ?? 0;
  const totalTickets = tenants?.reduce((sum, t) => sum + t.ticket_count, 0) ?? 0;
  const totalUsers = tenants?.reduce((sum, t) => sum + t.user_count, 0) ?? 0;

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-text-primary">Global Dashboard</h1>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard title="Tenants" value={totalTenants} icon={<Building2 size={20} />} />
        <StatCard title="Total Tickets" value={totalTickets} icon={<Ticket size={20} />} />
        <StatCard title="Total Users" value={totalUsers} icon={<Users size={20} />} />
      </div>

      {!tenants?.length ? (
        <EmptyState message="No tenants" />
      ) : (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <h2 className="text-sm font-semibold text-text-secondary">Tenants</h2>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">ID</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Name</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Status</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Plan</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Users</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Tickets</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-text-secondary">Last Activity</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((t: TenantListItem) => (
                <tr
                  key={t.customer_id}
                  className="border-b border-border-subtle hover:bg-elevated/30 cursor-pointer"
                  onClick={() => navigate(`/t/${t.customer_id}`)}
                >
                  <td className="px-4 py-3 text-text-primary font-mono text-xs">{t.customer_id}</td>
                  <td className="px-4 py-3 text-text-primary">{t.name}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-xs px-2 py-0.5 rounded border ${
                        t.status === "active"
                          ? "bg-green-500/15 text-green-400 border-green-500/30"
                          : "bg-amber-500/15 text-amber-400 border-amber-500/30"
                      }`}
                    >
                      {t.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs px-2 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/30">
                      {t.plan}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-text-secondary">{t.user_count}</td>
                  <td className="px-4 py-3 text-text-secondary">{t.ticket_count}</td>
                  <td className="px-4 py-3"><TimeAgo date={t.last_activity} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
