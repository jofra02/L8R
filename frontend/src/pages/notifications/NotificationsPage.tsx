import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { DataTable, type Column } from "@/components/common/DataTable";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { JsonViewer } from "@/components/common/JsonViewer";
import { useNotifications, useResendNotification } from "@/hooks/useNotifications";
import { usePagination } from "@/hooks/usePagination";
import { useAuth } from "@/hooks/useAuth";
import type { NotificationDelivery } from "@/api/types";

export function NotificationsPage() {
  const { tenantId } = useParams();
  const { hasPermission } = useAuth();
  const canManage = hasPermission("notifications:manage");
  const { page, pageSize, setPage, reset } = usePagination();
  const [status, setStatus] = useState("");
  const [eventType, setEventType] = useState("");
  const [ticketId, setTicketId] = useState("");
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const filters = {
    page,
    page_size: pageSize,
    ...(status && { status }),
    ...(eventType && { event_type: eventType }),
    ...(ticketId && { ticket_id: ticketId }),
  };

  const { data, isLoading } = useNotifications(filters);
  const resend = useResendNotification();

  const columns: Column<NotificationDelivery>[] = [
    {
      key: "event_type",
      header: "Event",
      render: (r) => <span className="font-mono text-xs text-accent">{r.event_type}</span>,
      className: "w-36",
    },
    {
      key: "ticket_id",
      header: "Ticket",
      render: (r) =>
        r.ticket_id ? (
          <Link to={`/t/${tenantId}/tickets/${r.ticket_id}`} className="font-mono text-xs text-text-secondary hover:text-accent hover:underline">
            {r.ticket_id.slice(0, 8)}
          </Link>
        ) : (
          <span className="text-text-muted text-xs">-</span>
        ),
      className: "w-24",
    },
    {
      key: "run_id",
      header: "Run",
      render: (r) =>
        r.run_id ? (
          <Link to={`/t/${tenantId}/runs/${r.run_id}`} className="font-mono text-xs text-text-secondary hover:text-accent hover:underline">
            {r.run_id.slice(0, 8)}
          </Link>
        ) : (
          <span className="text-text-muted text-xs">-</span>
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
      key: "attempts",
      header: "Attempts",
      render: (r) => <span className="text-xs text-text-secondary">{r.attempts}</span>,
      className: "w-20",
    },
    {
      key: "response_status",
      header: "HTTP",
      render: (r) =>
        r.response_status != null ? (
          <span className="font-mono text-xs text-text-secondary">{r.response_status}</span>
        ) : (
          <span className="text-text-muted text-xs">-</span>
        ),
      className: "w-16",
    },
    {
      key: "detail",
      header: "Detail",
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
      className: "w-16",
    },
    {
      key: "created_at",
      header: "Created",
      render: (r) => <TimeAgo date={r.created_at} />,
      className: "w-32",
    },
    {
      key: "actions",
      header: "",
      render: (r) =>
        canManage && r.status !== "pending" ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              resend.mutate(r.id);
            }}
            disabled={resend.isPending}
            title="Resend notification"
            className="inline-flex items-center gap-1 text-xs text-accent hover:underline disabled:opacity-50"
          >
            <RefreshCw size={12} className={resend.isPending ? "animate-spin" : ""} />
            Resend
          </button>
        ) : null,
      className: "w-24",
    },
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-text-primary">Notifications</h1>

      <div className="flex flex-wrap gap-3">
        <select
          value={eventType}
          onChange={(e) => { setEventType(e.target.value); reset(); }}
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">All Events</option>
          <option value="ticket.ingested">ticket.ingested</option>
          <option value="run.completed">run.completed</option>
        </select>
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); reset(); }}
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">All Statuses</option>
          <option value="pending">pending</option>
          <option value="delivered">delivered</option>
          <option value="failed">failed</option>
        </select>
        <input
          type="text"
          value={ticketId}
          onChange={(e) => { setTicketId(e.target.value); reset(); }}
          placeholder="Ticket ID..."
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
          emptyMessage="No notifications found"
        />
        {expandedRow != null && data?.items && (
          <div className="px-4 pb-4">
            {data.items
              .filter((r) => r.id === expandedRow)
              .map((r) => (
                <div key={r.id} className="bg-elevated border border-border rounded p-3 space-y-2">
                  {r.error && (
                    <div>
                      <span className="text-xs text-text-muted block mb-1">Error</span>
                      <span className="text-xs text-severity-critical">{r.error}</span>
                    </div>
                  )}
                  {r.response_body && (
                    <div>
                      <span className="text-xs text-text-muted block mb-1">Response</span>
                      <pre className="text-xs text-text-secondary whitespace-pre-wrap break-all max-h-40 overflow-y-auto">{r.response_body}</pre>
                    </div>
                  )}
                  <div>
                    <span className="text-xs text-text-muted block mb-1">Payload</span>
                    <JsonViewer data={r.payload} defaultExpanded />
                  </div>
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
