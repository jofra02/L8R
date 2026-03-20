import { useQuery } from "@tanstack/react-query";
import { queryAuditLogs, queryToolCalls } from "@/api/endpoints";

export function useAuditLogs(filters: Record<string, string | number | undefined>) {
  return useQuery({
    queryKey: ["audit-logs", filters],
    queryFn: () => queryAuditLogs(filters),
  });
}

export function useToolCalls(filters: Record<string, string | number | undefined>) {
  return useQuery({
    queryKey: ["tool-calls", filters],
    queryFn: () => queryToolCalls(filters),
  });
}
