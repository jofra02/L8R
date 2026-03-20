import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { BarChart3 } from "lucide-react";
import { DataTable, type Column } from "@/components/common/DataTable";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { useRunList } from "@/hooks/useRuns";
import { usePagination } from "@/hooks/usePagination";
import { formatDuration } from "@/lib/utils";
import { STATUS_OPTIONS } from "@/lib/constants";
import type { RunListItem } from "@/api/types";

export function RunListPage() {
  const navigate = useNavigate();
  const { page, pageSize, setPage, reset } = usePagination();
  const [status, setStatus] = useState("");
  const [ticketId, setTicketId] = useState("");

  const filters = {
    page,
    page_size: pageSize,
    ...(status && { status }),
    ...(ticketId && { ticket_id: ticketId }),
  };

  const { data, isLoading } = useRunList(filters);

  const columns: Column<RunListItem>[] = [
    {
      key: "id",
      header: "Run ID",
      render: (r) => <span className="font-mono text-xs text-text-secondary">{r.id.slice(0, 8)}</span>,
      className: "w-24",
    },
    {
      key: "ticket",
      header: "Ticket",
      render: (r) => (
        <button
          onClick={(e) => { e.stopPropagation(); navigate(`/tickets/${r.ticket_id}`); }}
          className="font-mono text-xs text-accent hover:underline"
        >
          {r.ticket_id.slice(0, 8)}
        </button>
      ),
      className: "w-24",
    },
    {
      key: "status",
      header: "Status",
      render: (r) => <StatusBadge value={r.status} type="status" />,
      className: "w-28",
    },
    {
      key: "decision",
      header: "Decision",
      render: (r) => <StatusBadge value={r.decision} type="decision" />,
      className: "w-28",
    },
    {
      key: "hypotheses",
      header: "Hypotheses",
      render: (r) => <span className="text-text-secondary text-sm">{r.hypothesis_count ?? "-"}</span>,
      className: "w-24",
    },
    {
      key: "duration",
      header: "Duration",
      render: (r) => {
        if (!r.ended_at || !r.started_at) return <span className="text-text-muted">-</span>;
        const dur = (new Date(r.ended_at).getTime() - new Date(r.started_at).getTime()) / 1000;
        return <span className="text-text-secondary text-sm">{formatDuration(dur)}</span>;
      },
      className: "w-24",
    },
    {
      key: "started",
      header: "Started",
      render: (r) => <TimeAgo date={r.started_at} />,
      className: "w-32",
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Runs</h1>
        <Link
          to="/runs/stats"
          className="flex items-center gap-2 bg-elevated border border-border text-sm text-text-secondary hover:text-text-primary px-3 py-1.5 rounded-md transition-colors"
        >
          <BarChart3 size={14} /> Statistics
        </Link>
      </div>

      <div className="flex flex-wrap gap-3">
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); reset(); }}
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">All Statuses</option>
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input
          type="text"
          value={ticketId}
          onChange={(e) => { setTicketId(e.target.value); reset(); }}
          placeholder="Filter by ticket ID..."
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent w-56"
        />
      </div>

      <div className="bg-card border border-border rounded-lg">
        <DataTable
          columns={columns}
          data={data?.items ?? []}
          loading={isLoading}
          page={page}
          totalPages={data?.total_pages}
          total={data?.total}
          onPageChange={setPage}
          onRowClick={(r) => navigate(`/runs/${r.id}`)}
          emptyMessage="No runs found"
        />
      </div>
    </div>
  );
}
