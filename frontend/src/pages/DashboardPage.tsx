import { Activity, CheckCircle, Clock, Zap } from "lucide-react";
import { useTenantNavigate } from "@/hooks/useTenantNavigate";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { StatCard } from "@/components/common/StatCard";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { useRunStats } from "@/hooks/useRuns";
import { useTicketList } from "@/hooks/useTickets";
import { useRunList } from "@/hooks/useRuns";
import { formatDuration, truncate } from "@/lib/utils";

const STATUS_CHART_COLORS: Record<string, string> = {
  completed: "#3fb950",
  running: "#2f81f7",
  pending: "#d29922",
  failed: "#f85149",
  error: "#f85149",
};

export function DashboardPage() {
  const navigate = useTenantNavigate();
  const { data: stats, isLoading: statsLoading } = useRunStats();
  const { data: recentTickets, isLoading: ticketsLoading } = useTicketList({ page: 1, page_size: 5 });
  const { data: recentRuns, isLoading: runsLoading } = useRunList({ page: 1, page_size: 5 });

  if (statsLoading) return <LoadingSpinner className="py-32" size="lg" />;

  const chartData = stats
    ? Object.entries(stats.by_status).map(([name, value]) => ({ name, value }))
    : [];

  const activeRuns = stats ? (stats.by_status["running"] ?? 0) : 0;

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-text-primary">Dashboard</h1>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Total Runs"
          value={stats?.total_runs ?? 0}
          icon={<Activity size={20} />}
        />
        <StatCard
          title="Success Rate"
          value={stats?.success_rate != null ? `${(stats.success_rate * 100).toFixed(1)}%` : "-"}
          icon={<CheckCircle size={20} />}
        />
        <StatCard
          title="Avg Duration"
          value={formatDuration(stats?.avg_duration_seconds)}
          icon={<Clock size={20} />}
        />
        <StatCard
          title="Active Runs"
          value={activeRuns}
          icon={<Zap size={20} />}
        />
      </div>

      {/* Bar Chart */}
      {chartData.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-5">
          <h2 className="text-sm font-semibold text-text-secondary mb-4">Runs by Status</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={chartData}>
              <XAxis
                dataKey="name"
                tick={{ fill: "#8b949e", fontSize: 12 }}
                axisLine={{ stroke: "#30363d" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "#8b949e", fontSize: 12 }}
                axisLine={{ stroke: "#30363d" }}
                tickLine={false}
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#161b22",
                  border: "1px solid #30363d",
                  borderRadius: "6px",
                  color: "#e6edf3",
                  fontSize: "12px",
                }}
              />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {chartData.map((entry) => (
                  <Cell key={entry.name} fill={STATUS_CHART_COLORS[entry.name] ?? "#8b949e"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Recent Tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Tickets */}
        <div className="bg-card border border-border rounded-lg">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <h2 className="text-sm font-semibold text-text-secondary">Recent Tickets</h2>
            <button
              onClick={() => navigate("/tickets")}
              className="text-xs text-accent hover:text-accent-hover transition-colors"
            >
              View all
            </button>
          </div>
          {ticketsLoading ? (
            <LoadingSpinner className="py-8" />
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {recentTickets?.items.map((t) => (
                  <tr
                    key={t.id}
                    onClick={() => navigate(`/tickets/${t.id}`)}
                    className="border-b border-border-subtle hover:bg-elevated/50 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-2.5">
                      <StatusBadge value={t.severity} type="severity" />
                    </td>
                    <td className="px-4 py-2.5 text-text-primary">{truncate(t.text, 50)}</td>
                    <td className="px-4 py-2.5">
                      <StatusBadge value={t.latest_run_status} type="status" />
                    </td>
                    <td className="px-4 py-2.5">
                      <TimeAgo date={t.created_at} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Recent Runs */}
        <div className="bg-card border border-border rounded-lg">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <h2 className="text-sm font-semibold text-text-secondary">Recent Runs</h2>
            <button
              onClick={() => navigate("/runs")}
              className="text-xs text-accent hover:text-accent-hover transition-colors"
            >
              View all
            </button>
          </div>
          {runsLoading ? (
            <LoadingSpinner className="py-8" />
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {recentRuns?.items.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => navigate(`/runs/${r.id}`)}
                    className="border-b border-border-subtle hover:bg-elevated/50 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-2.5 font-mono text-xs text-text-secondary">{r.id.slice(0, 8)}</td>
                    <td className="px-4 py-2.5">
                      <StatusBadge value={r.status} type="status" />
                    </td>
                    <td className="px-4 py-2.5">
                      <StatusBadge value={r.decision} type="decision" />
                    </td>
                    <td className="px-4 py-2.5">
                      <TimeAgo date={r.started_at} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
