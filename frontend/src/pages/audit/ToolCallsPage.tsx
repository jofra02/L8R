import { useState } from "react";
import { DataTable, type Column } from "@/components/common/DataTable";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { JsonViewer } from "@/components/common/JsonViewer";
import { useToolCalls } from "@/hooks/useAudit";
import { usePagination } from "@/hooks/usePagination";
import type { ToolCallResponse } from "@/api/types";

export function ToolCallsPage() {
  const { page, pageSize, setPage, reset } = usePagination();
  const [runId, setRunId] = useState("");
  const [toolName, setToolName] = useState("");
  const [status, setStatus] = useState("");
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const filters = {
    page,
    page_size: pageSize,
    ...(runId && { run_id: runId }),
    ...(toolName && { tool_name: toolName }),
    ...(status && { status }),
  };

  const { data, isLoading } = useToolCalls(filters);

  const columns: Column<ToolCallResponse>[] = [
    {
      key: "tool_name",
      header: "Tool",
      render: (r) => <span className="font-mono text-xs text-accent">{r.tool_name}</span>,
    },
    {
      key: "run_id",
      header: "Run",
      render: (r) => <span className="font-mono text-xs text-text-secondary">{r.run_id.slice(0, 8)}</span>,
      className: "w-24",
    },
    {
      key: "status",
      header: "Status",
      render: (r) => <StatusBadge value={r.status} type="status" />,
      className: "w-28",
    },
    {
      key: "error",
      header: "Error",
      render: (r) => r.error ? <span className="text-xs text-severity-critical">{r.error.slice(0, 50)}</span> : <span className="text-text-muted text-xs">-</span>,
    },
    {
      key: "args",
      header: "Args",
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
      key: "started_at",
      header: "Time",
      render: (r) => <TimeAgo date={r.started_at} />,
      className: "w-32",
    },
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-text-primary">Tool Calls</h1>

      <div className="flex flex-wrap gap-3">
        <input
          type="text"
          value={runId}
          onChange={(e) => { setRunId(e.target.value); reset(); }}
          placeholder="Run ID..."
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent w-48"
        />
        <input
          type="text"
          value={toolName}
          onChange={(e) => { setToolName(e.target.value); reset(); }}
          placeholder="Tool name..."
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent w-40"
        />
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); reset(); }}
          className="bg-elevated border border-border rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">All Statuses</option>
          <option value="success">success</option>
          <option value="error">error</option>
        </select>
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
          emptyMessage="No tool calls found"
        />
        {expandedRow != null && data?.items && (
          <div className="px-4 pb-4">
            {data.items
              .filter((r) => r.id === expandedRow)
              .map((r) => (
                <div key={r.id} className="bg-elevated border border-border rounded p-3 space-y-2">
                  <div>
                    <span className="text-xs text-text-muted block mb-1">Arguments</span>
                    <JsonViewer data={r.args_redacted} defaultExpanded />
                  </div>
                  <div>
                    <span className="text-xs text-text-muted block mb-1">Result</span>
                    <JsonViewer data={r.result_meta} defaultExpanded />
                  </div>
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
