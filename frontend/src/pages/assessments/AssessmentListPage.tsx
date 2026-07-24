import { useState } from "react";
import { useTenantNavigate } from "@/hooks/useTenantNavigate";
import { Plus, ClipboardCheck, Activity, Gauge, ShieldAlert } from "lucide-react";
import { DataTable, type Column } from "@/components/common/DataTable";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { StatCard } from "@/components/common/StatCard";
import { useAssessmentList, ASSESSMENT_ACTIVE_STATUSES } from "@/hooks/useAssessments";
import { usePagination } from "@/hooks/usePagination";
import type { AssessmentListItem } from "@/api/types";

const RUN_STATUS_OPTIONS = [
  "draft", "queued", "collecting", "evaluating",
  "completed", "completed_with_errors", "failed", "cancelled",
];

function ScoreCell({ item }: { item: AssessmentListItem }) {
  const score = item.score?.overall;
  if (score == null) return <span className="text-text-muted text-xs">-</span>;
  const coverage = item.score?.coverage;
  return (
    <div className="flex items-center gap-2">
      <span className="text-sm font-semibold text-text-primary">{score}</span>
      {coverage != null && coverage < 1 && (
        <span className="text-xs text-severity-medium" title="Score coverage is incomplete">
          {Math.round(coverage * 100)}% cov
        </span>
      )}
    </div>
  );
}

function ProgressCell({ item }: { item: AssessmentListItem }) {
  const p = item.progress;
  if (!ASSESSMENT_ACTIVE_STATUSES.includes(item.status)) {
    return <span className="text-text-muted text-xs">-</span>;
  }
  const total = p.phase === "evaluating" ? p.controls_total : p.steps_total;
  const done = p.phase === "evaluating" ? p.controls_done : p.steps_done;
  const pct = total ? Math.round(((done ?? 0) / total) * 100) : 0;
  return (
    <div className="flex items-center gap-2 min-w-[100px]">
      <div className="flex-1 h-1.5 bg-border rounded-full overflow-hidden">
        <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-text-secondary w-9 text-right">{pct}%</span>
    </div>
  );
}

export function AssessmentListPage() {
  const navigate = useTenantNavigate();
  const { page, pageSize, setPage, reset } = usePagination();
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");

  const filters = {
    page,
    page_size: pageSize,
    ...(status && { status }),
    ...(search && { search }),
  };

  const { data, isLoading } = useAssessmentList(filters);

  const items = data?.items ?? [];
  const running = items.filter((a) => ASSESSMENT_ACTIVE_STATUSES.includes(a.status)).length;
  const scored = items.filter((a) => a.score?.overall != null);
  const avgScore = scored.length
    ? Math.round(scored.reduce((s, a) => s + (a.score?.overall ?? 0), 0) / scored.length)
    : null;
  const criticalFindings = items.reduce((s, a) => s + (a.stats?.critical_findings ?? 0), 0);

  const columns: Column<AssessmentListItem>[] = [
    {
      key: "name",
      header: "Name",
      render: (r) => <span className="text-text-primary font-medium">{r.name}</span>,
    },
    {
      key: "definition",
      header: "Template",
      render: (r) => (
        <span className="text-xs text-text-secondary">
          {r.definition_id} <span className="text-text-muted">v{r.definition_version}</span>
        </span>
      ),
    },
    {
      key: "devices",
      header: "Devices",
      render: (r) => <span className="text-text-secondary">{r.device_count}</span>,
      className: "w-20",
    },
    {
      key: "status",
      header: "Status",
      render: (r) => <StatusBadge value={r.status} type="status" />,
      className: "w-40",
    },
    {
      key: "progress",
      header: "Progress",
      render: (r) => <ProgressCell item={r} />,
      className: "w-36",
    },
    {
      key: "score",
      header: "Score",
      render: (r) => <ScoreCell item={r} />,
      className: "w-28",
    },
    {
      key: "critical",
      header: "Critical",
      render: (r) => {
        const n = r.stats?.critical_findings ?? 0;
        return n > 0 ? (
          <span className="text-severity-critical font-semibold">{n}</span>
        ) : (
          <span className="text-text-muted text-xs">0</span>
        );
      },
      className: "w-20",
    },
    {
      key: "requested_by",
      header: "By",
      render: (r) => (
        <span className="text-xs text-text-secondary font-mono">
          {r.requested_by ? r.requested_by.slice(0, 8) : "-"}
        </span>
      ),
      className: "w-24",
    },
    {
      key: "created",
      header: "Created",
      render: (r) => <TimeAgo date={r.created_at} />,
      className: "w-32",
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Assessments</h1>
        <button
          onClick={() => navigate("/assessments/new")}
          className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors"
        >
          <Plus size={16} /> New Assessment
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Total" value={data?.total ?? 0} icon={<ClipboardCheck size={20} />} />
        <StatCard title="Running" value={running} icon={<Activity size={20} />} />
        <StatCard
          title="Avg Score"
          value={avgScore ?? "-"}
          icon={<Gauge size={20} />}
          subtitle={avgScore != null ? "across scored runs on this page" : undefined}
        />
        <StatCard title="Critical Findings" value={criticalFindings} icon={<ShieldAlert size={20} />} />
      </div>

      <div className="flex flex-wrap gap-3">
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); reset(); }}
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">All Statuses</option>
          {RUN_STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input
          type="text"
          value={search}
          onChange={(e) => { setSearch(e.target.value); reset(); }}
          placeholder="Search by name..."
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent w-48"
        />
      </div>

      <div className="bg-card border border-border rounded-lg">
        <DataTable
          columns={columns}
          data={items}
          loading={isLoading}
          page={page}
          totalPages={data?.total_pages}
          total={data?.total}
          onPageChange={setPage}
          onRowClick={(r) => navigate(`/assessments/${r.id}`)}
          emptyMessage="No assessments yet. Create one to evaluate your devices."
        />
      </div>
    </div>
  );
}
