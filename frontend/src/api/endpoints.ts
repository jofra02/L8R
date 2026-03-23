import client from "./client";
import type {
  AuthContext,
  LoginRequest,
  TokenResponse,
  ChangePasswordRequest,
  ApiKeyCreate,
  ApiKeyResponse,
  ApiKeyCreatedResponse,
  UserResponse,
  UserCreateRequest,
  ProfileResponse,
  PermissionResponse,
  AssignmentResponse,
  PaginatedResponse,
  TicketSubmit,
  TicketListItem,
  GlobalTicketListItem,
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
  InventoryOverview,
  FullInventoryResponse,
  InventoryComponent,
  InventoryDependency,
  InventoryBaseline,
  InventoryKnownChange,
  InventoryImport,
  ComponentCreate,
  ComponentUpdate,
  DependencyCreate,
  BaselineCreate,
  BaselineUpdate,
  KnownChangeCreate,
  KnownChangeUpdate,
  TenantListItem as TenantListItemType,
  TenantDetail as TenantDetailType,
  TenantCreate,
  TenantUpdate,
  TenantEndpointResponse,
  TenantScopeResponse,
  EndpointUpsert,
  ScopeCreate,
  ScopeUpdate,
  CascadeWarning,
} from "./types";

// --- Health ---
export async function getHealth(): Promise<HealthResponse> {
  const { data } = await client.get<HealthResponse>("/health", { baseURL: "" });
  return data;
}

// --- Auth ---
export async function login(body: LoginRequest): Promise<TokenResponse> {
  const { data } = await client.post<TokenResponse>("/auth/login", body);
  return data;
}

export async function refreshToken(refresh_token: string): Promise<TokenResponse> {
  const { data } = await client.post<TokenResponse>("/auth/refresh", { refresh_token });
  return data;
}

export async function logout(refresh_token: string): Promise<void> {
  await client.post("/auth/logout", { refresh_token });
}

export async function changePassword(body: ChangePasswordRequest): Promise<void> {
  await client.post("/auth/change-password", body);
}

export async function switchTenant(customer_id: string): Promise<TokenResponse> {
  const { data } = await client.post<TokenResponse>("/auth/switch-tenant", { customer_id });
  return data;
}

export async function getMe(): Promise<AuthContext> {
  const { data } = await client.get<AuthContext>("/auth/me");
  return data;
}

// --- API Keys ---
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

// --- Users ---
export async function listUsers(): Promise<UserResponse[]> {
  const { data } = await client.get<UserResponse[]>("/users");
  return data;
}

export async function createUser(body: UserCreateRequest): Promise<UserResponse> {
  const { data } = await client.post<UserResponse>("/users", body);
  return data;
}

export async function getUser(userId: string): Promise<UserResponse> {
  const { data } = await client.get<UserResponse>(`/users/${userId}`);
  return data;
}

export async function updateUser(userId: string, body: Partial<UserCreateRequest>): Promise<UserResponse> {
  const { data } = await client.patch<UserResponse>(`/users/${userId}`, body);
  return data;
}

export async function resetUserPassword(userId: string, new_password: string): Promise<void> {
  await client.post(`/users/${userId}/reset-password`, { new_password });
}

// --- Profiles ---
export async function listProfiles(): Promise<ProfileResponse[]> {
  const { data } = await client.get<ProfileResponse[]>("/profiles");
  return data;
}

export async function createProfile(body: { name: string; description: string; permission_ids: string[] }): Promise<ProfileResponse> {
  const { data } = await client.post<ProfileResponse>("/profiles", body);
  return data;
}

export async function deleteProfile(profileId: string): Promise<void> {
  await client.delete(`/profiles/${profileId}`);
}

export async function listPermissions(): Promise<PermissionResponse[]> {
  const { data } = await client.get<PermissionResponse[]>("/profiles/permissions");
  return data;
}

// --- Tenant Assignments ---
export async function listTenantUsers(customerId: string): Promise<AssignmentResponse[]> {
  const { data } = await client.get<AssignmentResponse[]>(`/tenants/${customerId}/users`);
  return data;
}

export async function assignUserToTenant(customerId: string, userId: string, profileId: string): Promise<AssignmentResponse> {
  const { data } = await client.post<AssignmentResponse>(`/tenants/${customerId}/users`, { user_id: userId, profile_id: profileId });
  return data;
}

export async function removeUserFromTenant(customerId: string, userId: string): Promise<void> {
  await client.delete(`/tenants/${customerId}/users/${userId}`);
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

interface GlobalTicketFilters extends TicketFilters {
  tenant?: string;
}

export async function listGlobalTickets(filters: GlobalTicketFilters = {}): Promise<PaginatedResponse<GlobalTicketListItem>> {
  const { data } = await client.get<PaginatedResponse<GlobalTicketListItem>>("/tickets/global", { params: filters });
  return data;
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

export async function cancelRun(runId: string): Promise<{ status: string; run_id: string }> {
  const { data } = await client.post<{ status: string; run_id: string }>(`/runs/${runId}/cancel`);
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

// --- Inventory ---
export async function getInventoryOverview(): Promise<InventoryOverview> {
  const { data } = await client.get<InventoryOverview>("/inventory");
  return data;
}

export async function getFullInventory(): Promise<FullInventoryResponse> {
  const { data } = await client.get<FullInventoryResponse>("/inventory/full");
  return data;
}

export async function importInventory(body: InventoryImport): Promise<FullInventoryResponse> {
  const { data } = await client.post<FullInventoryResponse>("/inventory/import", body);
  return data;
}

// Components
export async function listComponents(): Promise<InventoryComponent[]> {
  const { data } = await client.get<InventoryComponent[]>("/inventory/components");
  return data;
}

export async function createComponent(body: ComponentCreate): Promise<InventoryComponent> {
  const { data } = await client.post<InventoryComponent>("/inventory/components", body);
  return data;
}

export async function updateComponent(id: string, body: ComponentUpdate): Promise<InventoryComponent> {
  const { data } = await client.patch<InventoryComponent>(`/inventory/components/${id}`, body);
  return data;
}

export async function deleteComponent(id: string): Promise<void> {
  await client.delete(`/inventory/components/${id}`);
}

// Dependencies
export async function listDependencies(): Promise<InventoryDependency[]> {
  const { data } = await client.get<InventoryDependency[]>("/inventory/dependencies");
  return data;
}

export async function createDependency(body: DependencyCreate): Promise<InventoryDependency> {
  const { data } = await client.post<InventoryDependency>("/inventory/dependencies", body);
  return data;
}

export async function deleteDependency(sourceId: string, targetId: string, relation: string): Promise<void> {
  await client.delete("/inventory/dependencies", { params: { source_id: sourceId, target_id: targetId, relation } });
}

// Baselines
export async function listBaselines(): Promise<InventoryBaseline[]> {
  const { data } = await client.get<InventoryBaseline[]>("/inventory/baselines");
  return data;
}

export async function createBaseline(body: BaselineCreate): Promise<InventoryBaseline> {
  const { data } = await client.post<InventoryBaseline>("/inventory/baselines", body);
  return data;
}

export async function updateBaseline(componentId: string, metric: string, body: BaselineUpdate): Promise<InventoryBaseline> {
  const { data } = await client.patch<InventoryBaseline>(`/inventory/baselines/${componentId}/${metric}`, body);
  return data;
}

export async function deleteBaseline(componentId: string, metric: string): Promise<void> {
  await client.delete(`/inventory/baselines/${componentId}/${metric}`);
}

// Known Changes
export async function listKnownChanges(): Promise<InventoryKnownChange[]> {
  const { data } = await client.get<InventoryKnownChange[]>("/inventory/changes");
  return data;
}

export async function createKnownChange(body: KnownChangeCreate): Promise<InventoryKnownChange> {
  const { data } = await client.post<InventoryKnownChange>("/inventory/changes", body);
  return data;
}

export async function updateKnownChange(index: number, body: KnownChangeUpdate): Promise<InventoryKnownChange> {
  const { data } = await client.patch<InventoryKnownChange>(`/inventory/changes/${index}`, body);
  return data;
}

export async function deleteKnownChange(index: number): Promise<void> {
  await client.delete(`/inventory/changes/${index}`);
}

// --- Tenants ---
export async function listTenants(): Promise<TenantListItemType[]> {
  const { data } = await client.get<TenantListItemType[]>("/tenants");
  return data;
}

export async function createTenant(body: TenantCreate): Promise<TenantListItemType> {
  const { data } = await client.post<TenantListItemType>("/tenants", body);
  return data;
}

export async function getTenantDetail(customerId: string): Promise<TenantDetailType> {
  const { data } = await client.get<TenantDetailType>(`/tenants/${customerId}`);
  return data;
}

export async function updateTenant(customerId: string, body: TenantUpdate): Promise<TenantListItemType> {
  const { data } = await client.patch<TenantListItemType>(`/tenants/${customerId}`, body);
  return data;
}

export async function deleteTenant(customerId: string, force?: boolean): Promise<void> {
  await client.delete(`/tenants/${customerId}`, { params: force ? { force: true } : {} });
}

export async function suspendTenant(customerId: string): Promise<TenantListItemType> {
  const { data } = await client.post<TenantListItemType>(`/tenants/${customerId}/suspend`);
  return data;
}

export async function activateTenant(customerId: string): Promise<TenantListItemType> {
  const { data } = await client.post<TenantListItemType>(`/tenants/${customerId}/activate`);
  return data;
}

export async function getCascadeWarning(customerId: string): Promise<CascadeWarning> {
  const { data } = await client.get<CascadeWarning>(`/tenants/${customerId}/cascade-warning`);
  return data;
}

export async function getTenantEndpoints(customerId: string): Promise<TenantEndpointResponse | null> {
  const { data } = await client.get<TenantEndpointResponse | null>(`/tenants/${customerId}/endpoints`);
  return data;
}

export async function upsertTenantEndpoints(customerId: string, body: EndpointUpsert): Promise<TenantEndpointResponse> {
  const { data } = await client.put<TenantEndpointResponse>(`/tenants/${customerId}/endpoints`, body);
  return data;
}

export async function listTenantScopes(customerId: string): Promise<TenantScopeResponse[]> {
  const { data } = await client.get<TenantScopeResponse[]>(`/tenants/${customerId}/scopes`);
  return data;
}

export async function createTenantScope(customerId: string, body: ScopeCreate): Promise<TenantScopeResponse> {
  const { data } = await client.post<TenantScopeResponse>(`/tenants/${customerId}/scopes`, body);
  return data;
}

export async function updateTenantScope(customerId: string, scopeId: number, body: ScopeUpdate): Promise<TenantScopeResponse> {
  const { data } = await client.patch<TenantScopeResponse>(`/tenants/${customerId}/scopes/${scopeId}`, body);
  return data;
}

export async function deleteTenantScope(customerId: string, scopeId: number): Promise<void> {
  await client.delete(`/tenants/${customerId}/scopes/${scopeId}`);
}
