// --- Auth ---
export interface AuthContext {
  customer_id: string;
  role: string;
  key_id: string;
}

export interface ApiKeyCreate {
  name: string;
  role: string;
  expires_at?: string | null;
}

export interface ApiKeyResponse {
  id: string;
  key_prefix: string;
  name: string;
  role: string;
  is_active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiKeyCreatedResponse extends ApiKeyResponse {
  raw_key: string;
}

// --- Pagination ---
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface PaginationParams {
  page: number;
  page_size: number;
}

// --- Tickets ---
export interface TicketSubmit {
  source?: string;
  mode?: string;
  severity?: string;
  text: string;
  external_id?: string;
  raw_payload?: Record<string, unknown>;
}

export interface TicketListItem {
  id: string;
  external_id: string | null;
  mode: string;
  severity: string;
  source: string;
  text: string;
  created_at: string;
  updated_at: string;
  latest_run_status: string | null;
  latest_run_decision: string | null;
}

export interface TicketDetail extends TicketListItem {
  raw_payload: Record<string, unknown> | null;
  run_count: number;
  latest_run_id: string | null;
  latest_run_final_answer: string | null;
}

export interface TicketTimelineEvent {
  id: number;
  run_id: string;
  seq: number;
  node: string;
  created_at: string;
  input_summary: Record<string, unknown> | null;
  output_summary: Record<string, unknown> | null;
}

export interface EvidenceItem {
  id: string;
  tool_name: string;
  content_hash: string;
  storage_ref: string;
  summary: string;
  created_at: string;
}

export interface HypothesisItem {
  id: string | null;
  title: string;
  description: string;
  confidence: number | null;
  status: string | null;
  evidence_refs: string[];
}

export interface FactItem {
  key: string;
  value: unknown;
  source_evidence_id: string | null;
  confidence: number | null;
}

export interface PlanResponse {
  diagnosis_steps: Record<string, unknown>[];
  remediation_steps: Record<string, unknown>[];
  validation_steps: Record<string, unknown>[];
  rollback_steps: Record<string, unknown>[];
}

export interface TicketReportResponse {
  ticket_id: string;
  job_id: string;
  status: string;
  report: string;
}

// --- Runs ---
export interface RunListItem {
  id: string;
  ticket_id: string;
  status: string;
  decision: string | null;
  hypothesis_count: number | null;
  started_at: string;
  ended_at: string | null;
}

export interface RunDetail extends RunListItem {
  trace_id: string;
  final_answer: string | null;
  cost_json: Record<string, unknown> | null;
  state_json: Record<string, unknown> | null;
}

export interface RunTimelineEvent {
  id: number;
  seq: number;
  node: string;
  created_at: string;
  input_json: Record<string, unknown> | null;
  output_json: Record<string, unknown> | null;
}

export interface RunToolCall {
  id: string;
  tool_name: string;
  args_redacted: Record<string, unknown>;
  result_meta: Record<string, unknown>;
  status: string;
  error: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface RunStats {
  total_runs: number;
  by_status: Record<string, number>;
  by_decision: Record<string, number>;
  avg_duration_seconds: number | null;
  success_rate: number | null;
}

// --- Audit ---
export interface AuditLogResponse {
  id: number;
  ticket_id: string;
  actor: string;
  action: string;
  details: Record<string, unknown>;
  timestamp: string;
}

export interface ToolCallResponse {
  id: string;
  run_id: string;
  tool_name: string;
  args_redacted: Record<string, unknown>;
  result_meta: Record<string, unknown>;
  status: string;
  error: string | null;
  started_at: string;
  ended_at: string | null;
}

// --- Submit response ---
export interface SubmitResponse {
  status: string;
  ticket_id: string;
  job_id: string;
}

// --- Health ---
export interface HealthResponse {
  status: string;
  app: string;
}
