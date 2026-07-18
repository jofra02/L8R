import { useQuery } from "@tanstack/react-query";
import {
  listAssessmentDefinitions,
  getAssessmentDefinition,
  listAssessments,
  getAssessmentDetail,
  listAssessmentSteps,
  listAssessmentResults,
  getAssessmentEvidence,
  getAssessmentReport,
} from "@/api/endpoints";

/** Statuses with a live background task — drives polling. */
export const ASSESSMENT_ACTIVE_STATUSES = ["queued", "collecting", "evaluating"];

const POLL_MS = 2500;

export function useAssessmentDefinitions() {
  return useQuery({
    queryKey: ["assessment-definitions"],
    queryFn: listAssessmentDefinitions,
  });
}

export function useAssessmentDefinition(definitionId: string, version: string) {
  return useQuery({
    queryKey: ["assessment-definition", definitionId, version],
    queryFn: () => getAssessmentDefinition(definitionId, version),
    enabled: !!definitionId && !!version,
  });
}

export function useAssessmentList(filters: Record<string, string | number | undefined>) {
  return useQuery({
    queryKey: ["assessments", filters],
    queryFn: () => listAssessments(filters),
    refetchInterval: (query) =>
      query.state.data?.items?.some((a) => ASSESSMENT_ACTIVE_STATUSES.includes(a.status))
        ? POLL_MS
        : false,
  });
}

export function useAssessmentDetail(runId: string) {
  return useQuery({
    queryKey: ["assessment", runId],
    queryFn: () => getAssessmentDetail(runId),
    enabled: !!runId,
    refetchInterval: (query) =>
      query.state.data && ASSESSMENT_ACTIVE_STATUSES.includes(query.state.data.status)
        ? POLL_MS
        : false,
  });
}

export function useAssessmentSteps(runId: string, active: boolean) {
  return useQuery({
    queryKey: ["assessment", runId, "steps"],
    queryFn: () => listAssessmentSteps(runId),
    enabled: !!runId,
    refetchInterval: active ? POLL_MS : false,
  });
}

export function useAssessmentResults(
  runId: string,
  filters: { target_id?: string; status?: string; severity?: string; category?: string },
  enabled = true,
) {
  return useQuery({
    queryKey: ["assessment", runId, "results", filters],
    queryFn: () => listAssessmentResults(runId, filters),
    enabled: !!runId && enabled,
  });
}

export function useAssessmentEvidence(runId: string, executionId: string | null) {
  return useQuery({
    queryKey: ["assessment", runId, "evidence", executionId],
    queryFn: () => getAssessmentEvidence(runId, executionId ?? ""),
    enabled: !!runId && !!executionId,
  });
}

export function useAssessmentReport(runId: string, enabled = true) {
  return useQuery({
    queryKey: ["assessment", runId, "report"],
    queryFn: () => getAssessmentReport(runId),
    enabled: !!runId && enabled,
    retry: false,
  });
}
