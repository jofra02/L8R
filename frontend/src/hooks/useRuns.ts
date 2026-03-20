import { useQuery } from "@tanstack/react-query";
import {
  listRuns,
  getRunDetail,
  getRunTimeline,
  getRunToolCalls,
  getRunStats,
} from "@/api/endpoints";

export function useRunList(filters: Record<string, string | number | undefined>) {
  return useQuery({
    queryKey: ["runs", filters],
    queryFn: () => listRuns(filters),
  });
}

export function useRunDetail(runId: string) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRunDetail(runId),
    enabled: !!runId,
  });
}

export function useRunTimeline(runId: string) {
  return useQuery({
    queryKey: ["run", runId, "timeline"],
    queryFn: () => getRunTimeline(runId),
    enabled: !!runId,
  });
}

export function useRunToolCalls(runId: string) {
  return useQuery({
    queryKey: ["run", runId, "tool-calls"],
    queryFn: () => getRunToolCalls(runId),
    enabled: !!runId,
  });
}

export function useRunStats(params?: { date_from?: string; date_to?: string }) {
  return useQuery({
    queryKey: ["run-stats", params],
    queryFn: () => getRunStats(params),
  });
}
