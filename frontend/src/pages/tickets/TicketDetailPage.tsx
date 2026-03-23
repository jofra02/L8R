import { useState } from "react";
import { useParams } from "react-router-dom";
import { useTenantNavigate } from "@/hooks/useTenantNavigate";
import { RefreshCw, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { EmptyState } from "@/components/common/EmptyState";
import { JsonViewer } from "@/components/common/JsonViewer";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import {
  useTicketDetail,
  useTicketTimeline,
  useTicketEvidence,
  useTicketHypotheses,
  useTicketFacts,
  useTicketPlan,
  useTicketReport,
  useRetryTicket,
} from "@/hooks/useTickets";
import { formatDate } from "@/lib/utils";
import { cn } from "@/lib/utils";

const TABS = ["Overview", "Timeline", "Evidence", "Hypotheses", "Facts", "Plan", "Report"] as const;
type Tab = (typeof TABS)[number];

export function TicketDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useTenantNavigate();
  const [activeTab, setActiveTab] = useState<Tab>("Overview");
  const ticketId = id ?? "";

  const { data: ticket, isLoading } = useTicketDetail(ticketId);
  const retry = useRetryTicket();

  if (isLoading) return <LoadingSpinner className="py-32" size="lg" />;
  if (!ticket) return <EmptyState title="Ticket not found" />;

  async function handleRetry() {
    try {
      await retry.mutateAsync(ticketId);
      toast.success("Pipeline re-run triggered");
    } catch {
      toast.error("Failed to retry");
    }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold text-text-primary font-mono">{ticket.id.slice(0, 12)}...</h1>
            <StatusBadge value={ticket.severity} type="severity" />
            <StatusBadge value={ticket.mode} type="status" />
            <StatusBadge value={ticket.latest_run_status} type="status" />
            {ticket.latest_run_decision && (
              <StatusBadge value={ticket.latest_run_decision} type="decision" />
            )}
          </div>
          <p className="text-xs text-text-muted">
            Created <TimeAgo date={ticket.created_at} /> | {ticket.run_count} run(s)
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleRetry}
            disabled={retry.isPending}
            className="flex items-center gap-2 bg-elevated border border-border text-sm text-text-secondary hover:text-text-primary px-3 py-1.5 rounded-md transition-colors"
          >
            <RefreshCw size={14} className={retry.isPending ? "animate-spin" : ""} /> Retry
          </button>
          {ticket.latest_run_id && (
            <button
              onClick={() => navigate(`/runs/${ticket.latest_run_id}`)}
              className="flex items-center gap-2 bg-elevated border border-border text-sm text-text-secondary hover:text-text-primary px-3 py-1.5 rounded-md transition-colors"
            >
              <ExternalLink size={14} /> View Run
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
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

      {/* Tab Content */}
      <div className="bg-card border border-border rounded-lg p-5">
        {activeTab === "Overview" && <OverviewTab ticket={ticket} />}
        {activeTab === "Timeline" && <TimelineTab ticketId={ticketId} />}
        {activeTab === "Evidence" && <EvidenceTab ticketId={ticketId} />}
        {activeTab === "Hypotheses" && <HypothesesTab ticketId={ticketId} />}
        {activeTab === "Facts" && <FactsTab ticketId={ticketId} />}
        {activeTab === "Plan" && <PlanTab ticketId={ticketId} />}
        {activeTab === "Report" && <ReportTab ticketId={ticketId} />}
      </div>
    </div>
  );
}

function OverviewTab({ ticket }: { ticket: import("@/api/types").TicketDetail }) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-xs font-semibold text-text-secondary uppercase mb-2">Description</h3>
        <p className="text-sm text-text-primary whitespace-pre-wrap">{ticket.text}</p>
      </div>
      {ticket.external_id && (
        <div>
          <h3 className="text-xs font-semibold text-text-secondary uppercase mb-1">External ID</h3>
          <p className="text-sm font-mono text-text-secondary">{ticket.external_id}</p>
        </div>
      )}
      {ticket.raw_payload && (
        <div>
          <h3 className="text-xs font-semibold text-text-secondary uppercase mb-2">Raw Payload</h3>
          <JsonViewer data={ticket.raw_payload} />
        </div>
      )}
    </div>
  );
}

function TimelineTab({ ticketId }: { ticketId: string }) {
  const { data, isLoading } = useTicketTimeline(ticketId);
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
              {event.output_summary && (
                <JsonViewer data={event.output_summary} className="mt-1" />
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EvidenceTab({ ticketId }: { ticketId: string }) {
  const { data, isLoading } = useTicketEvidence(ticketId);
  if (isLoading) return <LoadingSpinner className="py-8" />;
  if (!data?.length) return <EmptyState message="No evidence collected" />;

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-border">
          <th className="text-left px-4 py-2 text-xs font-semibold text-text-secondary">Tool</th>
          <th className="text-left px-4 py-2 text-xs font-semibold text-text-secondary">Summary</th>
          <th className="text-left px-4 py-2 text-xs font-semibold text-text-secondary">Collected</th>
        </tr>
      </thead>
      <tbody>
        {data.map((e) => (
          <tr key={e.id} className="border-b border-border-subtle">
            <td className="px-4 py-2 font-mono text-xs text-accent">{e.tool_name}</td>
            <td className="px-4 py-2 text-text-primary">{e.summary}</td>
            <td className="px-4 py-2"><TimeAgo date={e.created_at} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function HypothesesTab({ ticketId }: { ticketId: string }) {
  const { data, isLoading } = useTicketHypotheses(ticketId);
  if (isLoading) return <LoadingSpinner className="py-8" />;
  if (!data?.length) return <EmptyState message="No hypotheses generated" />;

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {data.map((h, i) => (
        <div key={h.id ?? i} className="bg-elevated border border-border rounded-lg p-4 space-y-2">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-medium text-text-primary">{h.title}</h4>
            {h.status && <StatusBadge value={h.status} type="status" />}
          </div>
          <p className="text-xs text-text-secondary">{h.description}</p>
          {h.confidence != null && (
            <div className="flex items-center gap-2">
              <div className="flex-1 h-1.5 bg-border rounded-full overflow-hidden">
                <div
                  className="h-full bg-accent rounded-full"
                  style={{ width: `${h.confidence * 100}%` }}
                />
              </div>
              <span className="text-xs text-text-muted">{(h.confidence * 100).toFixed(0)}%</span>
            </div>
          )}
          {h.evidence_refs.length > 0 && (
            <p className="text-xs text-text-muted">{h.evidence_refs.length} evidence ref(s)</p>
          )}
        </div>
      ))}
    </div>
  );
}

function FactsTab({ ticketId }: { ticketId: string }) {
  const { data, isLoading } = useTicketFacts(ticketId);
  if (isLoading) return <LoadingSpinner className="py-8" />;
  if (!data?.length) return <EmptyState message="No facts extracted" />;

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-border">
          <th className="text-left px-4 py-2 text-xs font-semibold text-text-secondary">Key</th>
          <th className="text-left px-4 py-2 text-xs font-semibold text-text-secondary">Value</th>
          <th className="text-left px-4 py-2 text-xs font-semibold text-text-secondary">Source</th>
          <th className="text-left px-4 py-2 text-xs font-semibold text-text-secondary">Confidence</th>
        </tr>
      </thead>
      <tbody>
        {data.map((f, i) => (
          <tr key={i} className="border-b border-border-subtle">
            <td className="px-4 py-2 font-mono text-xs text-accent">{f.key}</td>
            <td className="px-4 py-2 text-text-primary text-xs">
              {typeof f.value === "string" ? f.value : JSON.stringify(f.value)}
            </td>
            <td className="px-4 py-2 font-mono text-xs text-text-muted">
              {f.source_evidence_id ? f.source_evidence_id.slice(0, 8) : "-"}
            </td>
            <td className="px-4 py-2 text-xs text-text-secondary">
              {f.confidence != null ? `${(f.confidence * 100).toFixed(0)}%` : "-"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PlanTab({ ticketId }: { ticketId: string }) {
  const { data, isLoading } = useTicketPlan(ticketId);
  if (isLoading) return <LoadingSpinner className="py-8" />;
  if (!data) return <EmptyState message="No resolution plan" />;

  const sections = [
    { label: "Diagnosis", steps: data.diagnosis_steps },
    { label: "Remediation", steps: data.remediation_steps },
    { label: "Validation", steps: data.validation_steps },
    { label: "Rollback", steps: data.rollback_steps },
  ].filter((s) => s.steps.length > 0);

  if (sections.length === 0) return <EmptyState message="No resolution plan" />;

  return (
    <div className="space-y-4">
      {sections.map((section) => (
        <PlanSection key={section.label} label={section.label} steps={section.steps} />
      ))}
    </div>
  );
}

function PlanSection({ label, steps }: { label: string; steps: Record<string, unknown>[] }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 bg-elevated/50 text-sm font-medium text-text-primary hover:bg-elevated transition-colors"
      >
        <span>{label} ({steps.length} steps)</span>
        <span className="text-text-muted">{open ? "-" : "+"}</span>
      </button>
      {open && (
        <div className="p-4 space-y-2">
          {steps.map((step, i) => (
            <div key={i} className="flex gap-3">
              <span className="text-xs text-text-muted mt-0.5 w-5 text-right flex-shrink-0">{i + 1}.</span>
              <div className="text-sm text-text-secondary">
                {typeof step === "string" ? step : <JsonViewer data={step} />}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ReportTab({ ticketId }: { ticketId: string }) {
  const { data, isLoading, error } = useTicketReport(ticketId);
  if (isLoading) return <LoadingSpinner className="py-8" />;
  if (error || !data?.report) return <EmptyState message="No report available" />;

  return <MarkdownRenderer content={data.report} />;
}
