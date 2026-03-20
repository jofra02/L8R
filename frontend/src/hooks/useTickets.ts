import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listTickets,
  getTicketDetail,
  getTicketTimeline,
  getTicketEvidence,
  getTicketHypotheses,
  getTicketFacts,
  getTicketPlan,
  getTicketReport,
  submitTicket,
  retryTicket,
} from "@/api/endpoints";
import type { TicketSubmit } from "@/api/types";

export function useTicketList(filters: Record<string, string | number | undefined>) {
  return useQuery({
    queryKey: ["tickets", filters],
    queryFn: () => listTickets(filters),
  });
}

export function useTicketDetail(ticketId: string) {
  return useQuery({
    queryKey: ["ticket", ticketId],
    queryFn: () => getTicketDetail(ticketId),
    enabled: !!ticketId,
  });
}

export function useTicketTimeline(ticketId: string) {
  return useQuery({
    queryKey: ["ticket", ticketId, "timeline"],
    queryFn: () => getTicketTimeline(ticketId),
    enabled: !!ticketId,
  });
}

export function useTicketEvidence(ticketId: string) {
  return useQuery({
    queryKey: ["ticket", ticketId, "evidence"],
    queryFn: () => getTicketEvidence(ticketId),
    enabled: !!ticketId,
  });
}

export function useTicketHypotheses(ticketId: string) {
  return useQuery({
    queryKey: ["ticket", ticketId, "hypotheses"],
    queryFn: () => getTicketHypotheses(ticketId),
    enabled: !!ticketId,
  });
}

export function useTicketFacts(ticketId: string) {
  return useQuery({
    queryKey: ["ticket", ticketId, "facts"],
    queryFn: () => getTicketFacts(ticketId),
    enabled: !!ticketId,
  });
}

export function useTicketPlan(ticketId: string) {
  return useQuery({
    queryKey: ["ticket", ticketId, "plan"],
    queryFn: () => getTicketPlan(ticketId),
    enabled: !!ticketId,
  });
}

export function useTicketReport(ticketId: string) {
  return useQuery({
    queryKey: ["ticket", ticketId, "report"],
    queryFn: () => getTicketReport(ticketId),
    enabled: !!ticketId,
  });
}

export function useSubmitTicket() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TicketSubmit) => submitTicket(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tickets"] });
    },
  });
}

export function useRetryTicket() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticketId: string) => retryTicket(ticketId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tickets"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}
