import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Square, RefreshCcw, ChevronDown, ChevronRight, AlertTriangle } from "lucide-react";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TimeAgo } from "@/components/common/TimeAgo";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { EmptyState } from "@/components/common/EmptyState";
import { JsonViewer } from "@/components/common/JsonViewer";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import { StatCard } from "@/components/common/StatCard";
import {
  useAssessmentDetail,
  useAssessmentSteps,
  useAssessmentResults,
  useAssessmentEvidence,
  useAssessmentReport,
  ASSESSMENT_ACTIVE_STATUSES,
} from "@/hooks/useAssessments";
import { cancelAssessment, reevaluateAssessment } from "@/api/endpoints";
import { formatDuration, cn } from "@/lib/utils";
import type {
  AssessmentControlResult,
  AssessmentDetail,
  AssessmentExecution,
} from "@/api/types";

const RESULT_TABS = ["Summary", "Findings", "Controls", "Evidence", "Report"] as const;
type ResultTab = (typeof RESULT_TABS)[number];

const SEVERITIES = ["critical", "high", "medium", "low"];

export function AssessmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const runId = id ?? "";
  const queryClient = useQueryClient();
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  const { data: run, isLoading } = useAssessmentDetail(runId);

  const cancelMut = useMutation({
    mutationFn: () => cancelAssessment(runId),
    onSuccess: () => {
      toast.success("Assessment cancelled");
      setShowCancelConfirm(false);
      queryClient.invalidateQueries({ queryKey: ["assessment", runId] });
      queryClient.invalidateQueries({ queryKey: ["assessments"] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? "Failed to cancel assessment");
    },
  });

  const reevaluateMut = useMutation({
    mutationFn: () => reevaluateAssessment(runId),
    onSuccess: () => {
      toast.success("Re-evaluation started");
      queryClient.invalidateQueries({ queryKey: ["assessment", runId] });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? "Failed to re-evaluate");
    },
  });

  if (isLoading) return <LoadingSpinner className="py-32" size="lg" />;
  if (!run) return <EmptyState title="Assessment not found" />;

  const isActive = ASSESSMENT_ACTIVE_STATUSES.includes(run.status);
  const hasResults = ["completed", "completed_with_errors"].includes(run.status);
  const duration =
    run.finished_at && run.started_at
      ? (new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000
      : null;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold text-text-primary">{run.name}</h1>
            <StatusBadge value={run.status} type="status" />
          </div>
          <p className="text-xs text-text-muted">
            {run.definition_id} v{run.definition_version} · {run.device_count} device(s)
            {run.started_at && <> · Started <TimeAgo date={run.started_at} /></>}
            {duration != null && ` · Duration: ${formatDuration(duration)}`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {isActive && (
            <button
              onClick={() => setShowCancelConfirm(true)}
              className="flex items-center gap-1.5 text-sm text-status-failed hover:text-red-300 transition-colors border border-status-failed/30 px-3 py-1.5 rounded-md hover:bg-status-failed/10"
            >
              <Square size={14} /> Cancel
            </button>
          )}
          {hasResults && (
            <button
              onClick={() => reevaluateMut.mutate()}
              disabled={reevaluateMut.isPending}
              className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary transition-colors border border-border px-3 py-1.5 rounded-md hover:bg-elevated disabled:opacity-50"
              title="Re-run the evaluation over the existing evidence"
            >
              <RefreshCcw size={14} /> Re-evaluate
            </button>
          )}
        </div>
      </div>

      {run.error && (
        <div className="border border-status-failed/30 bg-status-failed/10 rounded-md p-3 text-sm text-status-failed">
          {run.error}
        </div>
      )}

      {run.status === "completed_with_errors" && (
        <div className="flex items-center gap-2 border border-severity-medium/30 bg-severity-medium/10 rounded-md p-3 text-sm text-severity-medium">
          <AlertTriangle size={16} />
          Partial results: some collection steps or evaluations failed. The score covers
          only what could be evaluated.
        </div>
      )}

      {showCancelConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-card border border-border rounded-lg p-6 w-full max-w-md shadow-xl space-y-4">
            <h2 className="text-base font-semibold text-text-primary">Cancel this assessment?</h2>
            <p className="text-sm text-text-secondary">
              Collection will stop immediately. Evidence gathered so far is kept, but no
              evaluation will run.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowCancelConfirm(false)}
                className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
              >
                Keep running
              </button>
              <button
                onClick={() => cancelMut.mutate()}
                disabled={cancelMut.isPending}
                className="px-4 py-2 text-sm bg-status-failed/20 text-status-failed border border-status-failed/30 rounded-md hover:bg-status-failed/30 transition-colors disabled:opacity-50"
              >
                {cancelMut.isPending ? "Cancelling..." : "Cancel assessment"}
              </button>
            </div>
          </div>
        </div>
      )}

      {isActive || run.status === "draft" ? (
        <ProgressView run={run} />
      ) : hasResults ? (
        <ResultsView run={run} />
      ) : (
        // failed / cancelled: show what happened during collection
        <div className="bg-card border border-border rounded-lg p-5">
          <h3 className="text-xs font-semibold text-text-secondary uppercase mb-3">
            Collection steps
          </h3>
          <StepTable runId={run.id} run={run} active={false} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Progress view (live)
// ---------------------------------------------------------------------------

function ProgressView({ run }: { run: AssessmentDetail }) {
  const p = run.progress ?? {};
  const phase = p.phase ?? run.status;
  const isEvaluating = phase === "evaluating";
  const total = isEvaluating ? p.controls_total : p.steps_total;
  const done = isEvaluating ? p.controls_done : p.steps_done;
  const pct = total ? Math.round(((done ?? 0) / total) * 100) : 0;

  return (
    <div className="space-y-4">
      <div className="bg-card border border-border rounded-lg p-5 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm text-text-primary font-medium capitalize">
            {phase === "draft" ? "Not started" : `Phase: ${phase}`}
          </span>
          <span className="text-xs text-text-secondary">
            {done ?? 0} / {total ?? "?"} {isEvaluating ? "controls" : "steps"}
            {p.steps_failed ? ` · ${p.steps_failed} failed` : ""}
          </span>
        </div>
        <div className="h-2 bg-border rounded-full overflow-hidden">
          <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
        </div>
        <div className="flex flex-wrap gap-2">
          {run.targets.map((t) => (
            <span
              key={t.id}
              className="inline-flex items-center gap-2 px-2 py-1 rounded bg-elevated border border-border text-xs"
            >
              <span className="text-text-primary">{t.device_name}</span>
              <StatusBadge value={t.status} type="status" />
            </span>
          ))}
        </div>
      </div>

      <div className="bg-card border border-border rounded-lg p-5">
        <h3 className="text-xs font-semibold text-text-secondary uppercase mb-3">
          Collection steps
        </h3>
        <StepTable runId={run.id} run={run} active />
      </div>
    </div>
  );
}

function StepTable({ runId, run, active }: { runId: string; run: AssessmentDetail; active: boolean }) {
  const { data: steps, isLoading } = useAssessmentSteps(runId, active);
  const deviceByTarget = useMemo(
    () => Object.fromEntries(run.targets.map((t) => [t.id, t.device_name])),
    [run.targets],
  );

  if (isLoading) return <LoadingSpinner className="py-8" />;
  if (!steps?.length) return <EmptyState message="No collection activity yet" />;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            <th className="text-left px-3 py-2 text-xs font-semibold text-text-secondary">Device</th>
            <th className="text-left px-3 py-2 text-xs font-semibold text-text-secondary">Step</th>
            <th className="text-left px-3 py-2 text-xs font-semibold text-text-secondary">Tool</th>
            <th className="text-left px-3 py-2 text-xs font-semibold text-text-secondary">Status</th>
            <th className="text-left px-3 py-2 text-xs font-semibold text-text-secondary">Attempt</th>
            <th className="text-left px-3 py-2 text-xs font-semibold text-text-secondary">Duration</th>
            <th className="text-left px-3 py-2 text-xs font-semibold text-text-secondary">Error</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((s) => (
            <tr key={s.id} className="border-b border-border-subtle">
              <td className="px-3 py-2 text-text-secondary text-xs">{deviceByTarget[s.target_id] ?? "-"}</td>
              <td className="px-3 py-2 text-text-primary text-xs">{s.step_id}</td>
              <td className="px-3 py-2 font-mono text-xs text-accent">{s.tool_name}</td>
              <td className="px-3 py-2"><StatusBadge value={s.status} type="status" /></td>
              <td className="px-3 py-2 text-xs text-text-secondary">{s.attempt || "-"}</td>
              <td className="px-3 py-2 text-xs text-text-secondary">
                {s.duration_ms != null ? `${s.duration_ms} ms` : "-"}
              </td>
              <td className="px-3 py-2 text-xs text-text-muted max-w-[280px] truncate" title={s.error ?? ""}>
                {s.error_type ? `[${s.error_type}] ` : ""}{s.error ?? "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Results view (terminal)
// ---------------------------------------------------------------------------

function ResultsView({ run }: { run: AssessmentDetail }) {
  const [activeTab, setActiveTab] = useState<ResultTab>("Summary");

  return (
    <>
      <div className="border-b border-border flex gap-0">
        {RESULT_TABS.map((tab) => (
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
        {activeTab === "Summary" && <SummaryTab run={run} />}
        {activeTab === "Findings" && <ResultsTab run={run} findingsOnly />}
        {activeTab === "Controls" && <ResultsTab run={run} />}
        {activeTab === "Evidence" && <EvidenceTab run={run} />}
        {activeTab === "Report" && <ReportTab runId={run.id} />}
      </div>
    </>
  );
}

function SummaryTab({ run }: { run: AssessmentDetail }) {
  const score = run.score;
  const stats = run.stats;
  const bySeverity = stats?.findings_by_severity ?? {};
  const byCategory = score?.by_category ?? {};

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Score"
          value={score?.overall ?? "-"}
          subtitle={
            score?.coverage != null && score.coverage < 1
              ? `coverage ${Math.round(score.coverage * 100)}% — incomplete`
              : "full coverage"
          }
        />
        <StatCard
          title="Controls evaluated"
          value={`${score?.evaluated ?? 0} / ${score?.total ?? 0}`}
        />
        <StatCard title="Findings" value={stats?.findings_total ?? 0} />
        <StatCard title="Critical" value={stats?.critical_findings ?? 0} />
      </div>

      <div>
        <h3 className="text-xs font-semibold text-text-secondary uppercase mb-2">
          Findings by severity
        </h3>
        <div className="flex flex-wrap gap-3">
          {SEVERITIES.map((sev) => (
            <div key={sev} className="flex items-center gap-2">
              <StatusBadge value={sev} type="severity" />
              <span className="text-sm text-text-primary">{bySeverity[sev] ?? 0}</span>
            </div>
          ))}
        </div>
      </div>

      {Object.keys(byCategory).length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-text-secondary uppercase mb-2">
            Score by category
          </h3>
          <div className="space-y-2">
            {Object.entries(byCategory).map(([cat, s]) => (
              <div key={cat} className="flex items-center gap-3">
                <span className="text-xs text-text-secondary w-40 shrink-0">{cat}</span>
                <div className="flex-1 h-1.5 bg-border rounded-full overflow-hidden">
                  <div
                    className="h-full bg-accent"
                    style={{ width: `${s.score ?? 0}%` }}
                  />
                </div>
                <span className="text-xs text-text-primary w-12 text-right">
                  {s.score != null ? s.score : "n/a"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ResultsTab({ run, findingsOnly = false }: { run: AssessmentDetail; findingsOnly?: boolean }) {
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [targetId, setTargetId] = useState("");
  const { data: results, isLoading } = useAssessmentResults(run.id, {});
  const deviceByTarget = useMemo(
    () => Object.fromEntries(run.targets.map((t) => [t.id, t.device_name])),
    [run.targets],
  );

  const filtered = (results ?? []).filter((r) => {
    if (findingsOnly && !["fail", "warning"].includes(r.status)) return false;
    if (severity && r.severity !== severity) return false;
    if (status && r.status !== status) return false;
    if (targetId && r.target_id !== targetId) return false;
    return true;
  });

  if (isLoading) return <LoadingSpinner className="py-8" />;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <select
          value={severity}
          onChange={(e) => setSeverity(e.target.value)}
          className="bg-elevated border border-border rounded-md px-2 py-1 text-xs text-text-primary"
        >
          <option value="">All severities</option>
          {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {!findingsOnly && (
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="bg-elevated border border-border rounded-md px-2 py-1 text-xs text-text-primary"
          >
            <option value="">All statuses</option>
            {["pass", "fail", "warning", "not_applicable", "not_evaluated", "insufficient_evidence", "error"].map(
              (s) => <option key={s} value={s}>{s}</option>,
            )}
          </select>
        )}
        {run.targets.length > 1 && (
          <select
            value={targetId}
            onChange={(e) => setTargetId(e.target.value)}
            className="bg-elevated border border-border rounded-md px-2 py-1 text-xs text-text-primary"
          >
            <option value="">All devices</option>
            {run.targets.map((t) => (
              <option key={t.id} value={t.id}>{t.device_name}</option>
            ))}
          </select>
        )}
      </div>

      {!filtered.length ? (
        <EmptyState
          message={findingsOnly ? "No findings — all evaluated controls passed." : "No results"}
        />
      ) : (
        <div className="space-y-2">
          {filtered.map((r) => (
            <ControlResultRow key={r.id} result={r} device={deviceByTarget[r.target_id]} runId={run.id} />
          ))}
        </div>
      )}
    </div>
  );
}

function ControlResultRow({
  result,
  device,
  runId,
}: {
  result: AssessmentControlResult;
  device?: string;
  runId: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data: steps } = useAssessmentSteps(runId, false);

  const citedExecutions: AssessmentExecution[] = useMemo(() => {
    if (!steps || !result.evidence_refs) return [];
    const stepIds = new Set(result.evidence_refs.map((e) => e.step_id));
    return steps.filter((s) => s.target_id === result.target_id && stepIds.has(s.step_id));
  }, [steps, result]);

  return (
    <div className="border border-border-subtle rounded-md">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-elevated/50 transition-colors"
      >
        {expanded ? <ChevronDown size={14} className="text-text-muted shrink-0" /> : <ChevronRight size={14} className="text-text-muted shrink-0" />}
        <span className="font-mono text-xs text-text-muted w-28 shrink-0">{result.control_id}</span>
        <span className="text-sm text-text-primary flex-1">{result.title}</span>
        {device && <span className="text-xs text-text-secondary">{device}</span>}
        <StatusBadge value={result.severity} type="severity" />
        <StatusBadge value={result.status} type="control" />
      </button>

      {expanded && (
        <div className="px-9 pb-3 space-y-3 text-sm">
          <div className="flex items-center gap-4 text-xs text-text-muted">
            <span>category: {result.category}</span>
            <span>method: {result.method}</span>
            {result.confidence != null && <span>confidence: {Math.round(result.confidence * 100)}%</span>}
          </div>
          {result.explanation && (
            <div>
              <h4 className="text-xs font-semibold text-text-secondary uppercase mb-1">Explanation</h4>
              <MarkdownRenderer variant="compact" content={result.explanation} />
            </div>
          )}
          {result.recommendation && (
            <div>
              <h4 className="text-xs font-semibold text-text-secondary uppercase mb-1">Recommendation</h4>
              <MarkdownRenderer variant="compact" content={result.recommendation} />
            </div>
          )}
          {result.references && result.references.length > 0 && (
            <p className="text-xs text-text-muted">References: {result.references.join(" · ")}</p>
          )}
          {citedExecutions.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-text-secondary uppercase mb-1">Evidence</h4>
              <div className="space-y-2">
                {citedExecutions.map((e) => (
                  <EvidenceExpander key={e.id} runId={runId} execution={e} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EvidenceExpander({ runId, execution }: { runId: string; execution: AssessmentExecution }) {
  const [open, setOpen] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const { data: evidence, isLoading } = useAssessmentEvidence(runId, open ? execution.id : null);

  return (
    <div className="border border-border-subtle rounded-md">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left hover:bg-elevated/50 transition-colors"
      >
        {open ? <ChevronDown size={12} className="text-text-muted" /> : <ChevronRight size={12} className="text-text-muted" />}
        <span className="text-xs text-text-primary">{execution.step_id}</span>
        <span className="font-mono text-xs text-accent">{execution.tool_name}</span>
        {execution.truncated && <span className="text-xs text-severity-medium">truncated</span>}
      </button>
      {open && (
        <div className="px-3 pb-2 space-y-2">
          {isLoading ? (
            <LoadingSpinner className="py-4" size="sm" />
          ) : evidence ? (
            <>
              <div className="flex gap-2">
                <button
                  onClick={() => setShowRaw(false)}
                  className={cn("text-xs px-2 py-0.5 rounded border", !showRaw ? "border-accent text-accent" : "border-border text-text-secondary")}
                >
                  normalized
                </button>
                <button
                  onClick={() => setShowRaw(true)}
                  className={cn("text-xs px-2 py-0.5 rounded border", showRaw ? "border-accent text-accent" : "border-border text-text-secondary")}
                >
                  original
                </button>
              </div>
              <JsonViewer data={(showRaw ? evidence.raw : evidence.normalized) ?? {}} />
            </>
          ) : (
            <p className="text-xs text-text-muted">Evidence unavailable</p>
          )}
        </div>
      )}
    </div>
  );
}

function EvidenceTab({ run }: { run: AssessmentDetail }) {
  const { data: steps, isLoading } = useAssessmentSteps(run.id, false);
  const deviceByTarget = useMemo(
    () => Object.fromEntries(run.targets.map((t) => [t.id, t.device_name])),
    [run.targets],
  );

  if (isLoading) return <LoadingSpinner className="py-8" />;
  const collected = (steps ?? []).filter((s) => s.status === "success");
  if (!collected.length) return <EmptyState message="No evidence collected" />;

  return (
    <div className="space-y-2">
      {collected.map((s) => (
        <div key={s.id} className="flex items-center gap-3">
          <span className="text-xs text-text-secondary w-32 shrink-0">{deviceByTarget[s.target_id]}</span>
          <div className="flex-1">
            <EvidenceExpander runId={run.id} execution={s} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ReportTab({ runId }: { runId: string }) {
  const { data: report, isLoading } = useAssessmentReport(runId);
  if (isLoading) return <LoadingSpinner className="py-8" />;
  if (!report) return <EmptyState message="No report generated for this assessment" />;

  const model = report.model as any;
  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-xs font-semibold text-text-secondary uppercase mb-2">Executive summary</h3>
        <MarkdownRenderer content={String(model.executive_summary ?? "")} />
      </div>
      {Array.isArray(model.limitations) && model.limitations.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-text-secondary uppercase mb-2">Limitations</h3>
          <ul className="list-disc pl-5 text-sm text-text-secondary space-y-1">
            {model.limitations.map((l: string, i: number) => <li key={i}>{l}</li>)}
          </ul>
        </div>
      )}
      {model.methodology && (
        <div>
          <h3 className="text-xs font-semibold text-text-secondary uppercase mb-2">Methodology</h3>
          <p className="text-sm text-text-secondary">{model.methodology}</p>
        </div>
      )}
      <div>
        <h3 className="text-xs font-semibold text-text-secondary uppercase mb-2">Full report model</h3>
        <JsonViewer data={model} />
      </div>
      <p className="text-xs text-text-muted">
        Report format v{report.format_version}
        {report.generated_at && <> · generated <TimeAgo date={report.generated_at} /></>}
      </p>
    </div>
  );
}
