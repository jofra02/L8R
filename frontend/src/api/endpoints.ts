import client from "./client";
import type {
  AuthContext,
  ApiKeyCreate,
  ApiKeyResponse,
  ApiKeyCreatedResponse,
  PaginatedResponse,
  TicketSubmit,
  TicketListItem,
  TicketDetail,
  TicketTimelineEvent,
  EvidenceItem,
  HypothesisItem,
  FactItem,
  PlanResponse,
  TicketReportResponse,
  SubmitResponse,
  RunListItem,
  RunDetail,
  RunTimelineEvent,
  RunToolCall,
  RunStats,
  AuditLogResponse,
  ToolCallResponse,
  HealthResponse,
} from "./types";

// --- Health ---
export async function getHealth(): Promise<HealthResponse> {
  const { data } = await client.get<HealthResponse>("/health", { baseURL: "" });
  return data;
}

// --- Auth ---
export async function getMe(): Promise<AuthContext> {
  const { data } = await client.get<AuthContext>("/auth/me");
  return data;
}

export async function listApiKeys(): Promise<ApiKeyResponse[]> {
  const { data } = await client.get<ApiKeyResponse[]>("/auth/keys");
  return data;
}

export async function createApiKey(body: ApiKeyCreate): Promise<ApiKeyCreatedResponse> {
  const { data } = await client.post<ApiKeyCreatedResponse>("/auth/keys", body);
  return data;
}

export async function revokeApiKey(keyId: string): Promise<void> {
  await client.delete(`/auth/keys/${keyId}`);
}

export async function rotateApiKey(keyId: string): Promise<ApiKeyCreatedResponse> {
  const { data } = await client.post<ApiKeyCreatedResponse>(`/auth/keys/${keyId}/rotate`);
  return data;
}

// --- Tickets ---
interface TicketFilters {
  page?: number;
  page_size?: number;
  severity?: string;
  mode?: string;
  status?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
}

export async function listTickets(filters: TicketFilters = {}): Promise<PaginatedResponse<TicketListItem>> {
  const { data } = await client.get<PaginatedResponse<TicketListItem>>("/tickets", { params: filters });
  return data;
}

export async function getTicketDetail(ticketId: string): Promise<TicketDetail> {
  const { data } = await client.get<TicketDetail>(`/tickets/${ticketId}`);
  return data;
}

export async function getTicketTimeline(ticketId: string): Promise<TicketTimelineEvent[]> {
  const { data } = await client.get<TicketTimelineEvent[]>(`/tickets/${ticketId}/timeline`);
  return data;
}

export async function getTicketEvidence(ticketId: string): Promise<EvidenceItem[]> {
  const { data } = await client.get<EvidenceItem[]>(`/tickets/${ticketId}/evidence`);
  return data;
}

export async function getTicketHypotheses(ticketId: string): Promise<HypothesisItem[]> {
  const { data } = await client.get<HypothesisItem[]>(`/tickets/${ticketId}/hypotheses`);
  return data;
}

export async function getTicketFacts(ticketId: string): Promise<FactItem[]> {
  const { data } = await client.get<FactItem[]>(`/tickets/${ticketId}/facts`);
  return data;
}

export async function getTicketPlan(ticketId: string): Promise<PlanResponse> {
  const { data } = await client.get<PlanResponse>(`/tickets/${ticketId}/plan`);
  return data;
}

export async function getTicketReport(ticketId: string): Promise<TicketReportResponse> {
  const { data } = await client.get<TicketReportResponse>(`/tickets/${ticketId}/report`);
  return data;
}

export async function submitTicket(body: TicketSubmit): Promise<SubmitResponse> {
  const { data } = await client.post<SubmitResponse>("/tickets", body);
  return data;
}

export async function retryTicket(ticketId: string): Promise<SubmitResponse> {
  const { data } = await client.post<SubmitResponse>(`/tickets/${ticketId}/retry`);
  return data;
}

// --- Runs ---
interface RunFilters {
  page?: number;
  page_size?: number;
  status?: string;
  ticket_id?: string;
  date_from?: string;
  date_to?: string;
}

export async function listRuns(filters: RunFilters = {}): Promise<PaginatedResponse<RunListItem>> {
  const { data } = await client.get<PaginatedResponse<RunListItem>>("/runs", { params: filters });
  return data;
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  const { data } = await client.get<RunDetail>(`/runs/${runId}`);
  return data;
}

export async function getRunTimeline(runId: string): Promise<RunTimelineEvent[]> {
  const { data } = await client.get<RunTimelineEvent[]>(`/runs/${runId}/timeline`);
  return data;
}

export async function getRunToolCalls(runId: string): Promise<RunToolCall[]> {
  const { data } = await client.get<RunToolCall[]>(`/runs/${runId}/tool-calls`);
  return data;
}

export async function getRunStats(params?: { date_from?: string; date_to?: string }): Promise<RunStats> {
  const { data } = await client.get<RunStats>("/runs/stats", { params });
  return data;
}

// --- Audit ---
interface AuditFilters {
  page?: number;
  page_size?: number;
  ticket_id?: string;
  actor?: string;
  action?: string;
  date_from?: string;
  date_to?: string;
}

export async function queryAuditLogs(filters: AuditFilters = {}): Promise<PaginatedResponse<AuditLogResponse>> {
  const { data } = await client.get<PaginatedResponse<AuditLogResponse>>("/audit/logs", { params: filters });
  return data;
}

interface ToolCallFilters {
  page?: number;
  page_size?: number;
  run_id?: string;
  tool_name?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
}

export async function queryToolCalls(filters: ToolCallFilters = {}): Promise<PaginatedResponse<ToolCallResponse>> {
  const { data } = await client.get<PaginatedResponse<ToolCallResponse>>("/audit/tool-calls", { params: filters });
  return data;
}
