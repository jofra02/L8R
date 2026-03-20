import { useState } from "react";
import { DataTable, type Column } from "@/components/common/DataTable";
import { TimeAgo } from "@/components/common/TimeAgo";
import { JsonViewer } from "@/components/common/JsonViewer";
import { useAuditLogs } from "@/hooks/useAudit";
import { usePagination } from "@/hooks/usePagination";
import type { AuditLogResponse } from "@/api/types";

export function AuditLogsPage() {
  const { page, pageSize, setPage, reset } = usePagination();
  const [ticketId, setTicketId] = useState("");
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  const filters = {
    page,
    page_size: pageSize,
    ...(ticketId && { ticket_id: ticketId }),
    ...(actor && { actor }),
    ...(action && { action }),
  };

  const { data, isLoading } = useAuditLogs(filters);

  const columns: Column<AuditLogResponse>[] = [
    {
      key: "id",
      header: "ID",
      render: (r) => <span className="text-text-muted text-xs">{r.id}</span>,
      className: "w-16",
    },
    {
      key: "ticket_id",
      header: "Ticket",
      render: (r) => <span className="font-mono text-xs text-text-secondary">{r.ticket_id.slice(0, 8)}</span>,
      className: "w-24",
    },
    {
      key: "actor",
      header: "Actor",
      render: (r) => <span className="text-xs text-text-primary">{r.actor}</span>,
      className: "w-36",
    },
    {
      key: "action",
      header: "Action",
      render: (r) => <span className="text-xs font-mono text-accent">{r.action}</span>,
      className: "w-36",
    },
    {
      key: "details",
      header: "Details",
      render: (r) => (
        <button
          onClick={(e) => {
            e.stopPropagation();
            setExpandedRow(expandedRow === r.id ? null : r.id);
          }}
          className="text-xs text-accent hover:underline"
        >
          {expandedRow === r.id ? "Hide" : "Show"}
        </button>
      ),
      className: "w-20",
    },
    {
      key: "timestamp",
      header: "Time",
      render: (r) => <TimeAgo date={r.timestamp} />,
      className: "w-32",
    },
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-text-primary">Audit Logs</h1>

      <div className="flex flex-wrap gap-3">
        <input
          type="text"
          value={ticketId}
          onChange={(e) => { setTicketId(e.target.value); reset(); }}
          placeholder="Ticket ID..."
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent w-48"
        />
        <input
          type="text"
          value={actor}
          onChange={(e) => { setActor(e.target.value); reset(); }}
          placeholder="Actor..."
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent w-36"
        />
        <input
          type="text"
          value={action}
          onChange={(e) => { setAction(e.target.value); reset(); }}
          placeholder="Action..."
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent w-36"
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
          emptyMessage="No audit logs found"
        />
        {/* Expanded details */}
        {expandedRow != null && data?.items && (
          <div className="px-4 pb-4">
            {data.items
              .filter((r) => r.id === expandedRow)
              .map((r) => (
                <div key={r.id} className="bg-elevated border border-border rounded p-3">
                  <JsonViewer data={r.details} defaultExpanded />
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
