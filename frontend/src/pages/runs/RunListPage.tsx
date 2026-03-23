import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTenantNavigate } from "@/hooks/useTenantNavigate";
import { useTenantId } from "@/contexts/TenantContext";
import { BarChart3, Square } from "lucide-react";
import { DataTable, type Column } from "@/components/common/DataTable";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { useRunList } from "@/hooks/useRuns";
import { usePagination } from "@/hooks/usePagination";
import { cancelRun } from "@/api/endpoints";
import { formatDuration } from "@/lib/utils";
import { STATUS_OPTIONS } from "@/lib/constants";
import type { RunListItem } from "@/api/types";

export function RunListPage() {
  const navigate = useTenantNavigate();
  const tenantId = useTenantId();
  const queryClient = useQueryClient();
  const { page, pageSize, setPage, reset } = usePagination();
  const [status, setStatus] = useState("");
  const [ticketId, setTicketId] = useState("");
  const [cancelTarget, setCancelTarget] = useState<string | null>(null);

  const cancelMut = useMutation({
    mutationFn: (runId: string) => cancelRun(runId),
    onSuccess: () => {
      toast.success("Run cancelled");
      setCancelTarget(null);
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? "Failed to cancel run");
    },
  });

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
    {
      key: "actions",
      header: "",
      render: (r) =>
        r.status === "running" ? (
          <button
            onClick={(e) => { e.stopPropagation(); setCancelTarget(r.id); }}
            className="p-1 text-status-failed/70 hover:text-status-failed transition-colors"
            title="Stop run"
          >
            <Square size={14} />
          </button>
        ) : null,
      className: "w-10",
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Runs</h1>
        <Link
          to={`/t/${tenantId}/runs/stats`}
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

      {cancelTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-card border border-border rounded-lg p-6 w-full max-w-md shadow-xl space-y-4">
            <h2 className="text-base font-semibold text-text-primary">Stop this run?</h2>
            <p className="text-sm text-text-secondary">
              This will immediately stop the pipeline. Any partial results will be lost. Are you sure you want to cancel this run?
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setCancelTarget(null)}
                className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => cancelMut.mutate(cancelTarget)}
                disabled={cancelMut.isPending}
                className="px-4 py-2 text-sm bg-status-failed/20 text-status-failed border border-status-failed/30 rounded-md hover:bg-status-failed/30 transition-colors disabled:opacity-50"
              >
                {cancelMut.isPending ? "Stopping..." : "Stop Run"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
