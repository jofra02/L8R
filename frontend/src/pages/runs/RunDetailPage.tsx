import { useState } from "react";
import { useParams } from "react-router-dom";
import { useTenantNavigate } from "@/hooks/useTenantNavigate";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { EmptyState } from "@/components/common/EmptyState";
import { JsonViewer } from "@/components/common/JsonViewer";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import { useRunDetail, useRunTimeline, useRunToolCalls } from "@/hooks/useRuns";
import { formatDate, formatDuration, cn } from "@/lib/utils";

const TABS = ["Overview", "Timeline", "Tool Calls"] as const;
type Tab = (typeof TABS)[number];

export function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useTenantNavigate();
  const [activeTab, setActiveTab] = useState<Tab>("Overview");
  const runId = id ?? "";

  const { data: run, isLoading } = useRunDetail(runId);

  if (isLoading) return <LoadingSpinner className="py-32" size="lg" />;
  if (!run) return <EmptyState title="Run not found" />;

  const duration =
    run.ended_at && run.started_at
      ? (new Date(run.ended_at).getTime() - new Date(run.started_at).getTime()) / 1000
      : null;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold text-text-primary font-mono">{run.id.slice(0, 12)}...</h1>
            <StatusBadge value={run.status} type="status" />
            {run.decision && <StatusBadge value={run.decision} type="decision" />}
          </div>
          <p className="text-xs text-text-muted">
            Started <TimeAgo date={run.started_at} />
            {duration != null && ` | Duration: ${formatDuration(duration)}`}
            {` | Hypotheses: ${run.hypothesis_count ?? 0}`}
          </p>
        </div>
        <button
          onClick={() => navigate(`/tickets/${run.ticket_id}`)}
          className="text-sm text-accent hover:text-accent-hover transition-colors"
        >
          View Ticket
        </button>
      </div>

      <div className="border-b border-border flex gap-0">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              "px-4 py-2.5 text-sm transition-colors border-b-2",
              activeTab === tab
                ? "text-accent border-accent"
                : "text-text-secondary hover:text-text-primary border-transparent",
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="bg-card border border-border rounded-lg p-5">
        {activeTab === "Overview" && <RunOverview run={run} />}
        {activeTab === "Timeline" && <RunTimeline runId={runId} />}
        {activeTab === "Tool Calls" && <RunToolCallsTab runId={runId} />}
      </div>
    </div>
  );
}

function RunOverview({ run }: { run: import("@/api/types").RunDetail }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <span className="text-xs text-text-muted">Trace ID</span>
          <p className="font-mono text-text-secondary text-xs mt-0.5">{run.trace_id}</p>
        </div>
        <div>
          <span className="text-xs text-text-muted">Ticket ID</span>
          <p className="font-mono text-text-secondary text-xs mt-0.5">{run.ticket_id}</p>
        </div>
        <div>
          <span className="text-xs text-text-muted">Started</span>
          <p className="text-text-secondary text-xs mt-0.5">{formatDate(run.started_at)}</p>
        </div>
        <div>
          <span className="text-xs text-text-muted">Ended</span>
          <p className="text-text-secondary text-xs mt-0.5">{run.ended_at ? formatDate(run.ended_at) : "-"}</p>
        </div>
      </div>

      {run.final_answer && (
        <div>
          <h3 className="text-xs font-semibold text-text-secondary uppercase mb-2">Final Answer</h3>
          <MarkdownRenderer content={run.final_answer} />
        </div>
      )}

      {run.cost_json && (
        <div>
          <h3 className="text-xs font-semibold text-text-secondary uppercase mb-2">Cost</h3>
          <JsonViewer data={run.cost_json} />
        </div>
      )}
    </div>
  );
}

function RunTimeline({ runId }: { runId: string }) {
  const { data, isLoading } = useRunTimeline(runId);
  if (isLoading) return <LoadingSpinner className="py-8" />;
  if (!data?.length) return <EmptyState message="No timeline events" />;

  return (
    <div className="relative">
      <div className="absolute left-4 top-0 bottom-0 w-px bg-border" />
      <div className="space-y-4">
        {data.map((event) => (
          <div key={event.id} className="relative pl-10">
            <div className="absolute left-2.5 top-2 w-3 h-3 rounded-full bg-accent border-2 border-card" />
            <div className="space-y-1">
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium text-text-primary">{event.node}</span>
                <span className="text-xs text-text-muted">seq {event.seq}</span>
                <span className="text-xs text-text-muted">{formatDate(event.created_at)}</span>
              </div>
              {event.output_json && <JsonViewer data={event.output_json} className="mt-1" />}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RunToolCallsTab({ runId }: { runId: string }) {
  const { data, isLoading } = useRunToolCalls(runId);
  if (isLoading) return <LoadingSpinner className="py-8" />;
  if (!data?.length) return <EmptyState message="No tool calls" />;

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-border">
          <th className="text-left px-4 py-2 text-xs font-semibold text-text-secondary">Tool</th>
          <th className="text-left px-4 py-2 text-xs font-semibold text-text-secondary">Status</th>
          <th className="text-left px-4 py-2 text-xs font-semibold text-text-secondary">Started</th>
          <th className="text-left px-4 py-2 text-xs font-semibold text-text-secondary">Args</th>
        </tr>
      </thead>
      <tbody>
        {data.map((tc) => (
          <tr key={tc.id} className="border-b border-border-subtle">
            <td className="px-4 py-2 font-mono text-xs text-accent">{tc.tool_name}</td>
            <td className="px-4 py-2">
              <StatusBadge value={tc.status} type="status" />
            </td>
            <td className="px-4 py-2"><TimeAgo date={tc.started_at} /></td>
            <td className="px-4 py-2"><JsonViewer data={tc.args_redacted} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
