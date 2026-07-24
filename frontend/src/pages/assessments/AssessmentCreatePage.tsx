import { useMemo, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, Rocket, AlertTriangle } from "lucide-react";
import { useTenantNavigate } from "@/hooks/useTenantNavigate";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { EmptyState } from "@/components/common/EmptyState";
import { cn } from "@/lib/utils";
import { listComponents, createAssessment, startAssessment } from "@/api/endpoints";
import {
  useAssessmentDefinitions,
  useAssessmentDefinition,
} from "@/hooks/useAssessments";
import type { InventoryComponent } from "@/api/types";

const STEPS = ["Devices", "Template", "Scope Review", "Confirm"] as const;

const inputClass =
  "w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent";

export function AssessmentCreatePage() {
  const navigate = useTenantNavigate();
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [selectedDevices, setSelectedDevices] = useState<string[]>([]);
  const [definitionKey, setDefinitionKey] = useState<string>(""); // "<id>@<version>"
  const [warnings, setWarnings] = useState<string[] | null>(null);
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);

  const { data: components, isLoading: loadingComponents } = useQuery({
    queryKey: ["inventory-components"],
    queryFn: listComponents,
  });
  const { data: definitions, isLoading: loadingDefs } = useAssessmentDefinitions();

  const managedDevices = useMemo(
    () => (components ?? []).filter((c) => c.metadata?.mcp?.managed),
    [components],
  );

  const atIdx = definitionKey.indexOf("@");
  const definitionId = atIdx >= 0 ? definitionKey.slice(0, atIdx) : "";
  const definitionVersion = atIdx >= 0 ? definitionKey.slice(atIdx + 1) : "";
  const { data: definitionDetail } = useAssessmentDefinition(definitionId, definitionVersion);

  const createMut = useMutation({
    mutationFn: () =>
      createAssessment({
        name,
        definition_id: definitionId,
        definition_version: definitionVersion,
        component_ids: selectedDevices,
      }),
    onSuccess: (res) => {
      setPendingRunId(res.run.id);
      setWarnings(res.warnings);
      if (res.warnings.length === 0) {
        startMut.mutate(res.run.id);
      }
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? "Failed to create assessment");
    },
  });

  const startMut = useMutation({
    mutationFn: (runId: string) => startAssessment(runId),
    onSuccess: (run) => {
      toast.success("Assessment started");
      navigate(`/assessments/${run.id}`);
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? "Failed to start assessment");
    },
  });

  const toggleDevice = (id: string) =>
    setSelectedDevices((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id],
    );

  const canNext =
    (step === 0 && selectedDevices.length > 0) ||
    (step === 1 && !!definitionKey) ||
    step === 2 ||
    step === 3;

  const busy = createMut.isPending || startMut.isPending;

  return (
    <div className="space-y-4 max-w-4xl">
      <h1 className="text-lg font-semibold text-text-primary">New Assessment</h1>

      {/* Stepper */}
      <div className="border-b border-border flex gap-0">
        {STEPS.map((label, i) => (
          <button
            key={label}
            onClick={() => i < step && setStep(i)}
            disabled={i > step}
            className={cn(
              "px-4 py-2.5 text-sm transition-colors border-b-2",
              i === step
                ? "text-accent border-accent"
                : i < step
                  ? "text-text-primary border-transparent hover:text-accent"
                  : "text-text-muted border-transparent cursor-not-allowed",
            )}
          >
            {i + 1}. {label}
          </button>
        ))}
      </div>

      <div className="bg-card border border-border rounded-lg p-5 space-y-4">
        {step === 0 && (
          <DeviceStep
            devices={managedDevices}
            loading={loadingComponents}
            selected={selectedDevices}
            onToggle={toggleDevice}
          />
        )}

        {step === 1 && (
          <div className="space-y-3">
            <p className="text-sm text-text-secondary">
              Select the assessment template and version to apply.
            </p>
            {loadingDefs ? (
              <LoadingSpinner className="py-8" />
            ) : !definitions?.length ? (
              <EmptyState title="No templates" message="No assessment definitions are available." />
            ) : (
              <div className="space-y-2">
                {definitions.map((d) => {
                  const key = `${d.definition_id}@${d.version}`;
                  return (
                    <label
                      key={key}
                      className={cn(
                        "flex items-start gap-3 p-3 border rounded-md cursor-pointer transition-colors",
                        definitionKey === key
                          ? "border-accent bg-accent/5"
                          : "border-border hover:border-border hover:bg-elevated/50",
                      )}
                    >
                      <input
                        type="radio"
                        name="definition"
                        checked={definitionKey === key}
                        onChange={() => setDefinitionKey(key)}
                        className="mt-1 accent-[#2f81f7]"
                      />
                      <div>
                        <p className="text-sm text-text-primary font-medium">
                          {d.name} <span className="text-text-muted font-normal">v{d.version}</span>
                        </p>
                        <p className="text-xs text-text-secondary mt-0.5">
                          {d.vendor}/{d.product}
                          {d.description ? ` — ${d.description}` : ""}
                        </p>
                      </div>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <p className="text-sm text-text-secondary">
              Review what this assessment will collect and evaluate before running it.
            </p>
            {!definitionDetail ? (
              <LoadingSpinner className="py-8" />
            ) : (
              <>
                <div className="grid grid-cols-3 gap-4">
                  <ScopeStat label="Devices" value={selectedDevices.length} />
                  <ScopeStat label="Collection steps" value={definitionDetail.step_count} />
                  <ScopeStat label="Controls" value={definitionDetail.control_count} />
                </div>
                <div>
                  <h3 className="text-xs font-semibold text-text-secondary uppercase mb-2">
                    Categories evaluated
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {definitionDetail.categories.map((c) => (
                      <span
                        key={c}
                        className="px-2 py-0.5 rounded text-xs bg-elevated border border-border text-text-secondary"
                      >
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <h3 className="text-xs font-semibold text-text-secondary uppercase mb-2">
                    Collection steps (read-only tools)
                  </h3>
                  <div className="max-h-56 overflow-y-auto border border-border-subtle rounded-md">
                    <table className="w-full text-xs">
                      <tbody>
                        {definitionDetail.collection_steps.map((s: any) => (
                          <tr key={s.id} className="border-b border-border-subtle last:border-0">
                            <td className="px-3 py-1.5 text-text-primary">{s.id}</td>
                            <td className="px-3 py-1.5 font-mono text-accent">{s.tool}</td>
                            <td className="px-3 py-1.5 text-text-muted">
                              {s.required ? "required" : "optional"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
                <p className="text-xs text-text-muted">
                  Controls whose evidence cannot be collected will be reported as
                  insufficient evidence and excluded from the score.
                </p>
              </>
            )}
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <div>
              <label className="block text-xs text-text-secondary mb-1">Assessment name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={`${definitionDetail?.name ?? "Assessment"} — ${new Date().toISOString().slice(0, 10)}`}
                className={inputClass}
              />
            </div>
            <div className="text-sm text-text-secondary space-y-1">
              <p>
                <span className="text-text-primary font-medium">{selectedDevices.length}</span>{" "}
                device(s) · <span className="text-text-primary font-medium">{definitionDetail?.step_count ?? "?"}</span>{" "}
                collection steps · <span className="text-text-primary font-medium">{definitionDetail?.control_count ?? "?"}</span>{" "}
                controls
              </p>
              <p className="text-xs text-text-muted">
                Collection is strictly read-only: no configuration change is ever executed on the devices.
              </p>
            </div>

            {warnings && warnings.length > 0 && (
              <div className="border border-severity-medium/30 bg-severity-medium/10 rounded-md p-3 space-y-2">
                <p className="flex items-center gap-2 text-sm text-severity-medium font-medium">
                  <AlertTriangle size={16} /> Compatibility warnings
                </p>
                <ul className="text-xs text-text-secondary list-disc pl-5 space-y-1">
                  {warnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
                <button
                  onClick={() => pendingRunId && startMut.mutate(pendingRunId)}
                  disabled={busy}
                  className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors disabled:opacity-50"
                >
                  <Rocket size={14} /> {startMut.isPending ? "Starting..." : "Start anyway"}
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer nav */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => (step === 0 ? navigate("/assessments") : setStep(step - 1))}
          disabled={busy}
          className="flex items-center gap-1.5 px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors disabled:opacity-50"
        >
          <ChevronLeft size={16} /> {step === 0 ? "Cancel" : "Back"}
        </button>
        {step < 3 ? (
          <button
            onClick={() => setStep(step + 1)}
            disabled={!canNext}
            className="flex items-center gap-1.5 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors disabled:opacity-50"
          >
            Next <ChevronRight size={16} />
          </button>
        ) : (
          !warnings?.length && (
            <button
              onClick={() => {
                if (!name.trim()) {
                  toast.error("Give the assessment a name");
                  return;
                }
                createMut.mutate();
              }}
              disabled={busy}
              className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors disabled:opacity-50"
            >
              <Rocket size={14} /> {busy ? "Starting..." : "Create & Start"}
            </button>
          )
        )}
      </div>
    </div>
  );
}

function ScopeStat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="bg-elevated border border-border rounded-md p-3">
      <p className="text-xs text-text-secondary">{label}</p>
      <p className="text-xl font-bold text-text-primary mt-0.5">{value}</p>
    </div>
  );
}

function DeviceStep({
  devices,
  loading,
  selected,
  onToggle,
}: {
  devices: InventoryComponent[];
  loading: boolean;
  selected: string[];
  onToggle: (id: string) => void;
}) {
  if (loading) return <LoadingSpinner className="py-8" />;
  if (!devices.length) {
    return (
      <EmptyState
        title="No managed devices"
        message="No MCP-managed devices found in the inventory. Enable the MCP connection on a device first."
      />
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-text-secondary">
        Select the devices to assess. Only MCP-managed devices are shown.
      </p>
      <div className="space-y-2">
        {devices.map((d) => (
          <label
            key={d.id}
            className={cn(
              "flex items-center gap-3 p-3 border rounded-md cursor-pointer transition-colors",
              selected.includes(d.id)
                ? "border-accent bg-accent/5"
                : "border-border hover:bg-elevated/50",
            )}
          >
            <input
              type="checkbox"
              checked={selected.includes(d.id)}
              onChange={() => onToggle(d.id)}
              className="accent-[#2f81f7]"
            />
            <div className="flex-1">
              <p className="text-sm text-text-primary font-medium">{d.ref}</p>
              <p className="text-xs text-text-secondary">
                {d.metadata.mcp?.vendor}/{d.metadata.mcp?.appliance} · {d.metadata.mcp?.host}
              </p>
            </div>
            <span className="text-xs text-text-muted">{d.role}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
