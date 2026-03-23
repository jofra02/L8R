import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { DataTable, type Column } from "@/components/common/DataTable";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { truncate } from "@/lib/utils";
import { SEVERITY_OPTIONS, MODE_OPTIONS, STATUS_OPTIONS } from "@/lib/constants";
import { listGlobalTickets } from "@/api/endpoints";
import { listTenants } from "@/api/endpoints";
import type { GlobalTicketListItem } from "@/api/types";

export function GlobalTicketsPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const pageSize = 25;
  const [severity, setSeverity] = useState("");
  const [mode, setMode] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [tenant, setTenant] = useState("");

  const filters = {
    page,
    page_size: pageSize,
    ...(severity && { severity }),
    ...(mode && { mode }),
    ...(status && { status }),
    ...(search && { search }),
    ...(tenant && { tenant }),
  };

  const { data, isLoading } = useQuery({
    queryKey: ["global-tickets", filters],
    queryFn: () => listGlobalTickets(filters),
  });

  const { data: tenants } = useQuery({
    queryKey: ["tenants"],
    queryFn: listTenants,
  });

  const resetPage = () => setPage(1);

  const columns: Column<GlobalTicketListItem>[] = [
    {
      key: "tenant",
      header: "Tenant",
      render: (r) => (
        <span className="font-mono text-xs px-2 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/30">
          {r.customer_id}
        </span>
      ),
      className: "w-36",
    },
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
      render: (r) => <span className="text-text-primary">{truncate(r.text, 60)}</span>,
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
      <h1 className="text-lg font-semibold text-text-primary">Global Tickets</h1>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select
          value={tenant}
          onChange={(e) => { setTenant(e.target.value); resetPage(); }}
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">All Tenants</option>
          {tenants?.map((t) => (
            <option key={t.customer_id} value={t.customer_id}>{t.name || t.customer_id}</option>
          ))}
        </select>
        <select
          value={severity}
          onChange={(e) => { setSeverity(e.target.value); resetPage(); }}
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">All Severities</option>
          {SEVERITY_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select
          value={mode}
          onChange={(e) => { setMode(e.target.value); resetPage(); }}
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">All Modes</option>
          {MODE_OPTIONS.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); resetPage(); }}
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">All Statuses</option>
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input
          type="text"
          value={search}
          onChange={(e) => { setSearch(e.target.value); resetPage(); }}
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
          onRowClick={(r) => navigate(`/t/${r.customer_id}/tickets/${r.id}`)}
          emptyMessage="No tickets found"
        />
      </div>
    </div>
  );
}
