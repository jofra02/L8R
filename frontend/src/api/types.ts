// --- Auth ---
export interface AuthContext {
  user_id: string | null;
  key_id: string | null;
  auth_method: "jwt" | "api_key";
  customer_id: string;
  available_tenants: string[];
  role: string;
  profile_name: string;
  permissions: string[];
  is_platform_admin: boolean;
}

export interface LoginRequest {
  email: string;
  password: string;
  customer_id?: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token?: string;
  token_type: string;
  expires_in: number;
  must_change_password: boolean;
  user?: {
    id: string;
    email: string;
    display_name: string;
    is_platform_admin: boolean;
    customer_id: string;
    available_tenants: string[];
  };
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface ApiKeyCreate {
  name: string;
  expires_at?: string | null;
}

export interface ApiKeyResponse {
  id: string;
  key_prefix: string;
  name: string;
  is_active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiKeyCreatedResponse extends ApiKeyResponse {
  raw_key: string;
}

// --- Users ---
export interface UserResponse {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  is_platform_admin: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface UserCreateRequest {
  email: string;
  display_name: string;
  password: string;
  is_platform_admin?: boolean;
}

// --- Profiles ---
export interface PermissionResponse {
  id: string;
  resource: string;
  action: string;
  description: string;
}

export interface ProfileResponse {
  id: string;
  name: string;
  description: string;
  is_system: boolean;
  permissions: PermissionResponse[];
  created_at: string | null;
}

// --- Assignments ---
export interface AssignmentResponse {
  id: string;
  user_id: string;
  customer_id: string;
  profile_id: string;
  user_email: string | null;
  user_display_name: string | null;
  profile_name: string | null;
  created_at: string | null;
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

export interface GlobalTicketListItem extends TicketListItem {
  customer_id: string;
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

// --- Inventory ---
export interface InventoryComponent {
  id: string;
  ref: string;
  role: string;
  vendor: string | null;
  priority: number;
  metadata: Record<string, unknown>;
}

export interface InventoryDependency {
  source_id: string;
  target_id: string;
  relation: string;
  metadata: Record<string, unknown>;
}

export interface InventoryBaseline {
  component_id: string;
  metric: string;
  normal_value: string;
  description: string;
}

export interface InventoryKnownChange {
  index: number;
  date: string;
  description: string;
  component_id: string | null;
  change_type: string;
}

export interface InventoryOverview {
  customer_id: string;
  version: string;
  component_count: number;
  dependency_count: number;
  baseline_count: number;
  known_change_count: number;
}

export interface FullInventoryResponse {
  customer_id: string;
  version: string;
  components: InventoryComponent[];
  dependencies: InventoryDependency[];
  baselines: InventoryBaseline[];
  known_changes: InventoryKnownChange[];
}

export interface ComponentCreate {
  id: string;
  ref: string;
  role: string;
  vendor?: string;
  priority?: number;
  metadata?: Record<string, unknown>;
}

export interface ComponentUpdate {
  ref?: string;
  role?: string;
  vendor?: string;
  priority?: number;
  metadata?: Record<string, unknown>;
}

export interface DependencyCreate {
  source_id: string;
  target_id: string;
  relation: string;
  metadata?: Record<string, unknown>;
}

export interface BaselineCreate {
  component_id: string;
  metric: string;
  normal_value: string;
  description?: string;
}

export interface BaselineUpdate {
  normal_value?: string;
  description?: string;
}

export interface KnownChangeCreate {
  date: string;
  description: string;
  component_id?: string;
  change_type?: string;
}

export interface KnownChangeUpdate {
  date?: string;
  description?: string;
  component_id?: string;
  change_type?: string;
}

export interface InventoryImport {
  components: ComponentCreate[];
  dependencies: DependencyCreate[];
  baselines: BaselineCreate[];
  known_changes: KnownChangeCreate[];
}

// --- Tenants ---
export interface TenantListItem {
  customer_id: string;
  name: string;
  status: string;
  plan: string;
  user_count: number;
  ticket_count: number;
  last_activity: string | null;
  created_at: string;
  updated_at: string;
}

export interface TenantEndpointResponse {
  customer_id: string;
  pg_dsn_ref: string | null;
  qdrant_url_ref: string | null;
  object_store_ref: string | null;
}

export interface TenantScopeResponse {
  id: number;
  customer_id: string;
  scope_name: string;
  allowed_tools: string[];
  rate_limit: number | null;
  created_at: string;
}

export interface TenantDetail {
  customer_id: string;
  name: string;
  status: string;
  plan: string;
  created_at: string;
  updated_at: string;
  user_count: number;
  ticket_count: number;
  last_activity: string | null;
  endpoints: TenantEndpointResponse | null;
  scopes: TenantScopeResponse[];
}

export interface TenantCreate {
  customer_id: string;
  name: string;
  plan?: string;
}

export interface TenantUpdate {
  name?: string;
  plan?: string;
}

export interface EndpointUpsert {
  pg_dsn_ref?: string | null;
  qdrant_url_ref?: string | null;
  object_store_ref?: string | null;
}

export interface ScopeCreate {
  scope_name: string;
  allowed_tools: string[];
  rate_limit?: number | null;
}

export interface ScopeUpdate {
  scope_name?: string;
  allowed_tools?: string[];
  rate_limit?: number | null;
}

export interface CascadeWarning {
  user_count: number;
  ticket_count: number;
  api_key_count: number;
  message: string;
}

// --- Health ---
export interface HealthResponse {
  status: string;
  app: string;
}
