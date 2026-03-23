import { useState } from "react";
import { useTenantNavigate } from "@/hooks/useTenantNavigate";
import { Plus } from "lucide-react";
import { DataTable, type Column } from "@/components/common/DataTable";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { useTicketList } from "@/hooks/useTickets";
import { usePagination } from "@/hooks/usePagination";
import { truncate } from "@/lib/utils";
import { SEVERITY_OPTIONS, MODE_OPTIONS, STATUS_OPTIONS } from "@/lib/constants";
import { TicketSubmitModal } from "./TicketSubmitModal";
import type { TicketListItem } from "@/api/types";

export function TicketListPage() {
  const navigate = useTenantNavigate();
  const { page, pageSize, setPage, reset } = usePagination();
  const [severity, setSeverity] = useState("");
  const [mode, setMode] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [modalOpen, setModalOpen] = useState(false);

  const filters = {
    page,
    page_size: pageSize,
    ...(severity && { severity }),
    ...(mode && { mode }),
    ...(status && { status }),
    ...(search && { search }),
  };

  const { data, isLoading } = useTicketList(filters);

  const columns: Column<TicketListItem>[] = [
    {
      key: "id",
      header: "ID",
      render: (r) => <span className="font-mono text-xs text-text-secondary">{r.id.slice(0, 8)}</span>,
      className: "w-24",
    },
    {
      key: "severity",
      header: "Severity",
      render: (r) => <StatusBadge value={r.severity} type="severity" />,
      className: "w-24",
    },
    {
      key: "mode",
      header: "Mode",
      render: (r) => <span className="text-xs text-text-secondary">{r.mode}</span>,
      className: "w-24",
    },
    {
      key: "text",
      header: "Description",
      render: (r) => <span className="text-text-primary">{truncate(r.text, 80)}</span>,
    },
    {
      key: "status",
      header: "Status",
      render: (r) => <StatusBadge value={r.latest_run_status} type="status" />,
      className: "w-28",
    },
    {
      key: "decision",
      header: "Decision",
      render: (r) => <StatusBadge value={r.latest_run_decision} type="decision" />,
      className: "w-28",
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
        <h1 className="text-lg font-semibold text-text-primary">Tickets</h1>
        <button
          onClick={() => setModalOpen(true)}
          className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors"
        >
          <Plus size={16} /> New Ticket
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select
          value={severity}
          onChange={(e) => { setSeverity(e.target.value); reset(); }}
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">All Severities</option>
          {SEVERITY_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select
          value={mode}
          onChange={(e) => { setMode(e.target.value); reset(); }}
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">All Modes</option>
          {MODE_OPTIONS.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
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
          value={search}
          onChange={(e) => { setSearch(e.target.value); reset(); }}
          placeholder="Search..."
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent w-48"
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
          onRowClick={(r) => navigate(`/tickets/${r.id}`)}
          emptyMessage="No tickets found"
        />
      </div>

      <TicketSubmitModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </div>
  );
}
