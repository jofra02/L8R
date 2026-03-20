import { Activity, CheckCircle, Clock, Target } from "lucide-react";
import { BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { StatCard } from "@/components/common/StatCard";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { useRunStats } from "@/hooks/useRuns";
import { formatDuration } from "@/lib/utils";

const STATUS_COLORS: Record<string, string> = {
  completed: "#3fb950",
  running: "#2f81f7",
  pending: "#d29922",
  failed: "#f85149",
  error: "#f85149",
};

const DECISION_COLORS: Record<string, string> = {
  resolved: "#3fb950",
  escalate: "#f0883e",
  needs_human: "#d29922",
  blocked: "#f85149",
};

export function RunStatsPage() {
  const { data: stats, isLoading } = useRunStats();

  if (isLoading) return <LoadingSpinner className="py-32" size="lg" />;
  if (!stats) return null;

  const statusData = Object.entries(stats.by_status).map(([name, value]) => ({ name, value }));
  const decisionData = Object.entries(stats.by_decision).map(([name, value]) => ({ name, value }));

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-text-primary">Run Statistics</h1>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Total Runs" value={stats.total_runs} icon={<Activity size={20} />} />
        <StatCard
          title="Success Rate"
          value={stats.success_rate != null ? `${(stats.success_rate * 100).toFixed(1)}%` : "-"}
          icon={<CheckCircle size={20} />}
        />
        <StatCard
          title="Avg Duration"
          value={formatDuration(stats.avg_duration_seconds)}
          icon={<Clock size={20} />}
        />
        <StatCard
          title="Decisions"
          value={Object.keys(stats.by_decision).length}
          subtitle="distinct outcomes"
          icon={<Target size={20} />}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* By Status - Pie */}
        {statusData.length > 0 && (
          <div className="bg-card border border-border rounded-lg p-5">
            <h2 className="text-sm font-semibold text-text-secondary mb-4">By Status</h2>
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={statusData}
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  dataKey="value"
                  nameKey="name"
                  label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                  labelLine={false}
                  stroke="#0d1117"
                  strokeWidth={2}
                >
                  {statusData.map((entry) => (
                    <Cell key={entry.name} fill={STATUS_COLORS[entry.name] ?? "#8b949e"} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#161b22",
                    border: "1px solid #30363d",
                    borderRadius: "6px",
                    color: "#e6edf3",
                    fontSize: "12px",
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* By Decision - Bar */}
        {decisionData.length > 0 && (
          <div className="bg-card border border-border rounded-lg p-5">
            <h2 className="text-sm font-semibold text-text-secondary mb-4">By Decision</h2>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={decisionData}>
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
                  {decisionData.map((entry) => (
                    <Cell key={entry.name} fill={DECISION_COLORS[entry.name] ?? "#8b949e"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}
