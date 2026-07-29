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

// --- Notifications ---
export interface NotificationDelivery {
  id: string;
  event_type: string;
  ticket_id: string | null;
  run_id: string | null;
  payload: Record<string, unknown>;
  status: string;
  attempts: number;
  last_attempt_at: string | null;
  response_status: number | null;
  response_body: string | null;
  error: string | null;
  created_at: string;
}

// --- Submit response ---
export interface SubmitResponse {
  status: string;
  ticket_id: string;
  job_id: string;
}

// --- Inventory ---
export interface McpConnection {
  vendor?: string;
  appliance?: string;
  device_type?: string;
  os_version?: string;
  host: string;
  port?: number;
  token?: string; // write-only: forwarded to the gateway, never stored/returned
  verify_ssl?: boolean;
  primary?: boolean;
}

export interface McpSyncStatus {
  status: "synced" | "error" | "skipped";
  last_error?: string | null;
  last_synced_at?: string;
  warnings?: string[];
}

// Shape of metadata.mcp on managed components
export interface McpMetadata {
  managed: boolean;
  vendor: string;
  appliance: string;
  device_type: string;
  os_version?: string | null;
  host: string;
  port: number;
  verify_ssl: boolean;
  primary: boolean;
  sync?: McpSyncStatus;
}

export interface GatewaySync {
  status: "synced" | "error" | "skipped";
  reloaded?: boolean | null;
  error?: string | null;
  warnings?: string[];
}

export interface InventoryComponent {
  id: string;
  ref: string;
  role: string;
  vendor: string | null;
  priority: number;
  metadata: Record<string, unknown> & { mcp?: McpMetadata };
  gateway_sync?: GatewaySync | null;
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
  mcp_connection?: McpConnection;
}

export interface ComponentUpdate {
  ref?: string;
  role?: string;
  vendor?: string;
  priority?: number;
  metadata?: Record<string, unknown>;
  mcp_connection?: McpConnection;
  mcp_managed?: boolean; // false = detach the device from the gateway inventory
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

// --- Assessments ---
export interface AssessmentDefinitionItem {
  id: string;
  definition_id: string;
  version: string;
  vendor: string;
  product: string;
  name: string;
  description: string | null;
  created_at: string | null;
}

export interface AssessmentDefinitionDetail extends AssessmentDefinitionItem {
  step_count: number;
  control_count: number;
  categories: string[];
  collection_steps: Record<string, unknown>[];
  controls: Record<string, unknown>[];
}

export interface AssessmentTarget {
  id: string;
  component_id: string;
  device_name: string;
  status: string;
  error: string | null;
}

export interface AssessmentScore {
  scoring_version?: string;
  overall: number | null;
  coverage: number | null;
  evaluated?: number;
  total?: number;
  by_category?: Record<string, { score: number | null; coverage: number | null; evaluated: number; total: number }>;
  by_target?: Record<string, { score: number | null; coverage: number | null; evaluated: number; total: number }>;
}

export interface AssessmentStats {
  by_status?: Record<string, number>;
  findings_by_severity?: Record<string, number>;
  findings_total?: number;
  critical_findings?: number;
}

export interface AssessmentProgress {
  phase?: string;
  steps_total?: number;
  steps_done?: number;
  steps_failed?: number;
  controls_total?: number;
  controls_done?: number;
}

export interface AssessmentListItem {
  id: string;
  name: string;
  definition_id: string;
  definition_version: string;
  status: string;
  progress: AssessmentProgress;
  score: AssessmentScore | null;
  stats: AssessmentStats | null;
  requested_by: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  device_count: number;
}

export interface AssessmentDetail extends AssessmentListItem {
  params: Record<string, unknown>;
  error: string | null;
  targets: AssessmentTarget[];
}

export interface AssessmentCreate {
  name: string;
  definition_id: string;
  definition_version: string;
  component_ids: string[];
  params?: Record<string, unknown>;
}

export interface AssessmentCreateResponse {
  run: AssessmentDetail;
  warnings: string[];
}

export interface AssessmentExecution {
  id: string;
  target_id: string;
  step_id: string;
  tool_name: string;
  status: string;
  attempt: number;
  error_type: string | null;
  error: string | null;
  truncated: boolean;
  raw_size_bytes: number | null;
  duration_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface AssessmentControlResult {
  id: string;
  target_id: string;
  control_id: string;
  title: string;
  category: string;
  severity: string;
  status: string;
  method: string;
  confidence: number | null;
  explanation: string | null;
  recommendation: string | null;
  references: string[] | null;
  evidence_refs: { step_id: string }[] | null;
  created_at: string | null;
}

export interface AssessmentEvidence {
  execution_id: string;
  step_id: string;
  tool_name: string;
  raw: unknown;
  normalized: Record<string, unknown> | null;
  truncated: boolean;
  raw_size_bytes: number | null;
}

export interface AssessmentReport {
  run_id: string;
  format_version: string;
  generated_at: string | null;
  model: Record<string, unknown>;
}

// --- Assets ---
export interface AssetTypeField {
  key: string;
  label?: string | null;
  type: "string" | "integer" | "number" | "boolean" | "date" | "datetime" | "enum" | "string_list" | "ip" | "json";
  required: boolean;
  default?: unknown;
  enum?: string[] | null;
  filterable: boolean;
  searchable: boolean;
  sensitive: boolean;
  validation?: { pattern?: string | null; min?: number | null; max?: number | null; max_length?: number | null } | null;
}

export interface AssetTypeDef {
  type_id: string;
  version: number;
  label: string;
  category: string;
  roles: string[];
  open_attributes: boolean;
  fields: AssetTypeField[];
  relations: { allowed: string[] };
}

export interface Asset {
  id: string;
  customer_id: string;
  name: string;
  ref: string;
  asset_type: string;
  type_schema_version: number;
  manufacturer: string | null;
  model: string | null;
  serial_number: string | null;
  location: string | null;
  owner: string | null;
  ip_address: string | null;
  fqdn: string | null;
  status: string;
  criticality: string | null;
  tags: string[];
  purchase_date: string | null;
  warranty_expires: string | null;
  eol_date: string | null;
  attributes: Record<string, unknown>;
  provenance: Record<string, { source: string; pack_id?: string; run_id?: string; updated_at?: string }>;
  managed: boolean;
  mcp_config: (Record<string, unknown> & { device_type?: string; host?: string; sync_warnings?: string[] }) | null;
  sync_status: string | null;
  sync_error: string | null;
  last_synced_at: string | null;
  external_source: string | null;
  external_id: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  created_by: string | null;
  updated_by: string | null;
  gateway_sync?: GatewaySync | null;
}

export interface AssetCreatePayload {
  id?: string;
  name: string;
  ref?: string;
  asset_type: string;
  manufacturer?: string | null;
  model?: string | null;
  serial_number?: string | null;
  location?: string | null;
  owner?: string | null;
  ip_address?: string | null;
  fqdn?: string | null;
  status?: string;
  criticality?: string | null;
  tags?: string[];
  purchase_date?: string | null;
  warranty_expires?: string | null;
  eol_date?: string | null;
  attributes?: Record<string, unknown>;
  mcp_connection?: McpConnection | null;
}

export interface AssetUpdatePayload extends Partial<Omit<AssetCreatePayload, "id">> {
  mcp_managed?: boolean;
}

export interface AssetRelation {
  id: number;
  source_asset_id: string;
  target_asset_id: string;
  relation_type: string;
  provenance: string;
  details: Record<string, unknown>;
  created_at: string;
  source_name?: string | null;
  target_name?: string | null;
}

export interface AssetAuditEntry {
  id: number;
  asset_id: string;
  actor: string;
  action: string;
  changes: Record<string, unknown>;
  sync_run_id: string | null;
  created_at: string;
}

export interface AssetSyncRun {
  id: string;
  asset_id: string;
  pack_id: string;
  pack_version: number;
  status: string;
  trigger: string;
  started_at: string | null;
  finished_at: string | null;
  stats: Record<string, unknown> & { warnings?: string[] };
  error: string | null;
  created_at: string;
}

export interface AssetImportRowResult {
  row: number;
  action: "create" | "update" | "skip" | "error";
  asset_id: string | null;
  errors: string[];
}

export interface AssetImportResponse {
  dry_run: boolean;
  total: number;
  created: number;
  updated: number;
  skipped: number;
  failed: number;
  rows: AssetImportRowResult[];
}

export interface McpPack {
  vendor: string;
  appliance: string;
  version: string;
  display_name: string;
  device_type: string;
  prefix: string;
  pack_key: string;
}
