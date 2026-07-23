# API Reference

> Single source of truth for every HTTP surface of the platform. Generated from the code — when this document and the code disagree, the code wins; fix the document.

The platform exposes three HTTP surfaces:

| Surface | Base | Auth | Source |
|---|---|---|---|
| [Platform API](#platform-api) | `http://localhost:8000/api/v1` | `Authorization: Bearer <token>` (API key or JWT) | `src/api/app.py` + `src/api/routers/` |
| [Legacy ingestion](#legacy-ingestion) | `http://localhost:8000/api/v1` | `X-Customer-ID` header (outside RBAC) | `src/api/app.py:_mount_legacy_webhook` |
| [Gateway Admin API](#gateway-admin-api) | `http://localhost:8001` (MCP Gateway) | `X-Admin-Token` header | `mcp_gateway/gateway/admin_api.py` |

All responses are JSON. The Platform API is FastAPI (interactive docs at `/docs`), version `0.2.0`. CORS is fully open (`allow_origins=["*"]`) — restrict at the reverse proxy in production.

**Request skeleton** (Platform API):

```bash
curl -X <METHOD> "http://localhost:8000/api/v1/<resource>?customer_id=<tenant>" \
  -H "Authorization: Bearer <sk_live_... | JWT access token>" \
  -H "Content-Type: application/json" \
  -d '{
    "<field>": "<value>"
  }'
```

- `<METHOD>`: `GET` | `POST` | `PATCH` | `PUT` | `DELETE` — omit `-d` (and `Content-Type`) on `GET`/`DELETE`.
- `?customer_id=<tenant>`: only for platform admins acting on a tenant (see [impersonation](#platform-admin-impersonation)); tenant-scoped credentials omit it.
- Gateway Admin API requests use `-H "X-Admin-Token: $GATEWAY_ADMIN_TOKEN"` against port `8001` instead of the Bearer header.

---

## Authentication

Single dependency (`src/api/middleware/auth.py:get_auth_context`): every authenticated endpoint requires `Authorization: Bearer <token>`. The token is routed by prefix:

- **`sk_live_*` → API key.** Validated against the `api_keys` table (SHA-256 hash, active + not expired). API keys carry a **fixed, hardcoded permission set**: `tickets:write`, `tickets:read`, `runs:read` (`src/api/services/auth_service.py:_API_KEY_PERMISSIONS`). They are for machine ticket ingestion and polling — they cannot manage keys, users, tenants, or inventory, and any `role` concept does not apply to them (stored role is always `operator`, kept for backward compat).
- **Anything else → JWT.** Decoded access token claims: `sub` (user id), `cid` (customer_id), `perms` (permission list), `ipa` (is_platform_admin), `mcp` (must_change_password). JWT users get their permissions from the **profile** assigned to them per tenant (see [Profiles](#profiles--apiv1profiles) and [Assignments](#user-tenant-assignments--apiv1tenantscustomer_idusers)).

Authorization is **permission-based** (`require_permission`): an endpoint requires one permission; platform admins (`ipa: true`) pass every check. The legacy role hierarchy (`viewer < operator < tenant_admin < platform_admin`) is deprecated — kept only for backward compat in `require_role`.

### Platform admin impersonation

A platform admin's token is scoped to the sentinel tenant `__platform__`. To act on a specific tenant, pass `?customer_id=<tenant>` on any request — the context is re-scoped after verifying the tenant exists (404 `unknown_tenant` otherwise). Inventory endpoints **require** a concrete tenant and answer 400 `tenant_required` when called as `__platform__` without the override.

### Force password change

A JWT with `mcp: true` (fresh user, admin reset) is blocked from every route except `POST /auth/change-password`, `GET /auth/me`, and `POST /auth/logout` — anything else answers 403 `password_change_required`.

### Permission catalog

Seeded by migrations `b3f8a1c2d4e6` + `c4d5e6f7a8b9`:

`tickets:read`, `tickets:write`, `runs:read`, `evidence:read`, `audit:read`, `keys:read`, `keys:manage`, `users:read`, `users:manage`, `profiles:read`, `profiles:manage`, `tenants:read`, `tenants:manage`, `inventory:read`, `inventory:write`

Notes on actual enforcement:

- `evidence:read`, `keys:read`, `keys:manage` are seeded but **not enforced by any endpoint today**: evidence is served under `tickets:read`, and API-key management requires a JWT session with no specific permission (`_require_jwt_auth`).
- `POST /runs/{run_id}/cancel` requires only `runs:read` (not a write permission) — actual behavior, mind it when granting read-only profiles.

System profiles (seeded, immutable): **Super Admin** (all permissions), **Super Admin Read-Only** (all `:read`), **Tenant Admin** (everything except `tenants:manage` and `profiles:manage`).

### Common patterns

**Pagination** — paginated endpoints accept `page` (≥1, default 1) and `page_size` (1–100, default 25) and return `PaginatedResponse`:

```json
{"items": [...], "total": 142, "page": 1, "page_size": 25, "total_pages": 6}
```

**Date filters** — list endpoints accept optional `date_from` / `date_to` (ISO 8601, inclusive).

**Errors** — all non-2xx responses use `{"error": "<code>", "detail": "<message>"}`. Common codes:

| Status | Code | When |
|---|---|---|
| 401 | `invalid_auth` / `invalid_key` / `invalid_token` / `token_expired` | Missing or bad credentials |
| 403 | `insufficient_permissions` | Caller lacks the required permission |
| 403 | `jwt_required` | API key used on a JWT-only endpoint |
| 403 | `password_change_required` | `mcp` flag set, non-exempt route |
| 404 | `not_found` / `unknown_tenant` | Resource missing or not owned by the tenant |
| 409 | `invalid_state` / `email_exists` / `name_exists` | State or uniqueness conflict |
| 422 | — (FastAPI) | Request body fails Pydantic validation |

---

## Platform API

All routers mounted under `/api/v1`. Health endpoints are unauthenticated and live at the root.

### Health

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness: `{"status": "ok", "app": ...}` |
| GET | `/ready` | none | Readiness: `status` is `ready` \| `degraded` \| `initializing`, plus `tool_indexing` state |

The API is usable before tool-catalog indexing finishes; `search_tool_catalog` may return partial results until `/ready` reports `ready`. `degraded` means indexing failed (`tool_indexing.error` has the cause).

### Auth — `/api/v1/auth`

Source: `src/api/routers/auth.py`. Key management endpoints reject API-key auth (403 `jwt_required`).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/login` | none | Email + password → `TokenResponse` (401 `invalid_credentials`) |
| POST | `/auth/refresh` | none | Refresh token → new access token (401 `invalid_refresh_token`) |
| POST | `/auth/logout` | Bearer | Revoke a refresh token → 204 |
| POST | `/auth/change-password` | Bearer (JWT) | Change own password → 204 (400 `password_policy` / `invalid_password`) |
| POST | `/auth/switch-tenant` | Bearer (JWT) | New access token scoped to another tenant (403 `no_tenant_access`) |
| GET | `/auth/me` | Bearer | The caller's resolved `AuthContext` |
| POST | `/auth/keys` | Bearer (JWT only) | Create API key → 201, raw key returned **once** |
| GET | `/auth/keys` | Bearer (JWT only) | List the tenant's API keys |
| DELETE | `/auth/keys/{key_id}` | Bearer (JWT only) | Revoke a key → 204 (404 if missing/revoked) |
| POST | `/auth/keys/{key_id}/rotate` | Bearer (JWT only) | Revoke + reissue with same metadata; new raw key returned once |

**`POST /auth/login`** — body `LoginRequest {email, password, customer_id?}`:

```json
{
  "access_token": "eyJ...", "refresh_token": "...", "token_type": "bearer",
  "expires_in": 1800, "must_change_password": false, "user": {"...": "..."}
}
```

**`POST /auth/keys`** — body `ApiKeyCreate {name (1–128), expires_at?}`. Any other field (e.g. `role`) is ignored — keys always get the fixed permission set. Response 201 `ApiKeyCreatedResponse`:

```json
{
  "id": "550e8400-...", "key_prefix": "sk_live_abc1", "name": "ci-pipeline",
  "is_active": true, "expires_at": null, "last_used_at": null,
  "created_at": "2026-07-01T10:00:00Z",
  "raw_key": "sk_live_abc1234567890..."
}
```

`GET /auth/keys` returns the same shape without `raw_key` (`ApiKeyResponse[]`).

### Tickets — `/api/v1/tickets`

Source: `src/api/routers/tickets.py`. "Latest run" endpoints read the most recent `AgentRunORM.state_json` for the ticket.

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/tickets` | `tickets:write` | Submit a ticket; launches the Engineer run in background → 202 |
| GET | `/tickets` | `tickets:read` | Paginated tenant ticket list with filters |
| GET | `/tickets/global` | `tickets:read` + platform admin | Paginated cross-tenant list (adds `tenant` filter and `customer_id` per item) |
| GET | `/tickets/{ticket_id}` | `tickets:read` | `TicketDetail` (raw payload, run count, latest-run summary) |
| GET | `/tickets/{ticket_id}/timeline` | `tickets:read` | Agent events across all runs, ordered |
| GET | `/tickets/{ticket_id}/evidence` | `tickets:read` | `EvidenceItem[]` — evidence snapshot refs |
| GET | `/tickets/{ticket_id}/hypotheses` | `tickets:read` | `HypothesisItem[]` from the latest run |
| GET | `/tickets/{ticket_id}/facts` | `tickets:read` | `FactItem[]` (prefers `structured_facts`, falls back to flat `facts`) |
| GET | `/tickets/{ticket_id}/plan` | `tickets:read` | `PlanResponse` (diagnosis/remediation/validation/rollback steps) |
| GET | `/tickets/{ticket_id}/report` | `tickets:read` | Final markdown report (404 if the ticket has no runs) |
| POST | `/tickets/{ticket_id}/retry` | `tickets:write` | Re-run the same ticket → 202, new `job_id` |

List filters (`GET /tickets`, `GET /tickets/global`): `severity`, `mode`, `status` (latest run status), `search` (case-insensitive text match), `date_from`, `date_to`; `/global` adds `tenant`.

**`POST /tickets`** — body `TicketSubmit`:

| Field | Type | Default | Notes |
|---|---|---|---|
| `text` | str | — (required, ≥1 char) | Ticket description |
| `mode` | str | `incident` | `incident` \| `change` \| `validation` \| `inquiry` |
| `severity` | str | `medium` | `low` \| `medium` \| `high` \| `critical` |
| `source` | str | `api` | Source identifier |
| `external_id` | str? | null | External system ticket id |
| `raw_payload` | object? | null | Extra source-specific fields, preserved verbatim |

Response 202: `{"status": "accepted", "ticket_id": "...", "job_id": "..."}`. Execution is a fire-and-forget task in the API process — runs in flight are lost on restart (use `retry`).

**`GET /tickets/{id}/report`** — response `TicketReportResponse`:

```json
{"ticket_id": "TKT-abc123", "job_id": "550e8400-...", "status": "completed", "report": "# Diagnosis Report\n..."}
```

### Runs — `/api/v1/runs`

Source: `src/api/routers/runs.py`. All endpoints require `runs:read` (including `cancel` — see [enforcement notes](#permission-catalog)).

| Method | Path | Purpose |
|---|---|---|
| GET | `/runs` | Paginated run list; filters `status`, `ticket_id`, `date_from`, `date_to` |
| GET | `/runs/stats` | `RunStats` aggregate (`total_runs`, `by_status`, `by_decision`, `avg_duration_seconds`, `success_rate`); filters `date_from`, `date_to` |
| GET | `/runs/{run_id}` | `RunDetail` — includes `trace_id`, `final_answer`, `cost_json`, full `state_json` |
| GET | `/runs/{run_id}/timeline` | `RunTimelineEvent[]` ordered by `seq` (full `input_json`/`output_json`) |
| GET | `/runs/{run_id}/tool-calls` | `RunToolCall[]` — MCP tool audit trail (`args_redacted`, `result_meta`, `status`, `error`) |
| POST | `/runs/{run_id}/cancel` | Cancel a running execution → `{"status": "cancelled", "run_id"}`; 409 `invalid_state` if not `running` |

`RunListItem`: `{id, ticket_id, status, decision?, hypothesis_count?, started_at, ended_at?}`.

### Audit — `/api/v1/audit`

Source: `src/api/routers/audit.py`. Both require `audit:read`; both paginated.

| Method | Path | Filters | Returns |
|---|---|---|---|
| GET | `/audit/logs` | `ticket_id`, `actor`, `action`, `date_from`, `date_to` | `AuditLogResponse {id, ticket_id, actor, action, details, timestamp}` |
| GET | `/audit/tool-calls` | `run_id`, `tool_name`, `status`, `date_from`, `date_to` | `ToolCallResponse` (same shape as `RunToolCall` + `run_id`) |

### Users — `/api/v1/users`

Source: `src/api/routers/users.py` (models inline in the router). User accounts are global; tenant access is granted via [assignments](#user-tenant-assignments--apiv1tenantscustomer_idusers).

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/users` | `users:read` | List all users |
| POST | `/users` | `users:manage` | Create user → 201; always `must_change_password=true` (409 `email_exists`, 400 `password_policy`) |
| GET | `/users/{user_id}` | `users:read` | User detail |
| PATCH | `/users/{user_id}` | `users:manage` | Update `display_name`, `is_active`, `is_platform_admin` |
| POST | `/users/{user_id}/reset-password` | `users:manage` | Admin password reset → 204 |

`UserResponse`: `{id, email, display_name, is_active, is_platform_admin, must_change_password, last_login_at?, created_at}`.

### Profiles — `/api/v1/profiles`

Source: `src/api/routers/profiles.py` (models inline). A profile is a named permission set; system profiles cannot be modified or deleted (400 `invalid_operation`).

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/profiles` | `profiles:read` | List profiles (with their permissions) |
| POST | `/profiles` | `profiles:manage` | Create profile → 201 (`name`, `description`, `permission_ids[]`; 409 `name_exists`) |
| GET | `/profiles/permissions` | `profiles:read` | The full grantable [permission catalog](#permission-catalog) |
| GET | `/profiles/{profile_id}` | `profiles:read` | Profile detail |
| PATCH | `/profiles/{profile_id}` | `profiles:manage` | Update name/description/permissions |
| DELETE | `/profiles/{profile_id}` | `profiles:manage` | Delete → 204 |

### Tenants — `/api/v1/tenants`

Source: `src/api/routers/tenants.py`, schemas in `src/api/schemas/tenants.py`.

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/tenants` | `tenants:read` | List tenants (`TenantListItem[]`, not paginated) |
| POST | `/tenants` | `tenants:manage` | Create tenant → 201; also provisions the gateway inventory (`gateway_sync` in response) |
| GET | `/tenants/{customer_id}` | `tenants:read` | `TenantDetail` (+ `endpoints`, `scopes`) |
| PATCH | `/tenants/{customer_id}` | `tenants:manage` | Update `name` / `plan` |
| DELETE | `/tenants/{customer_id}?force=bool` | `tenants:manage` | Delete → 204; DB cascades remove all tenant rows |
| POST | `/tenants/{customer_id}/suspend` | `tenants:manage` | Suspend |
| POST | `/tenants/{customer_id}/activate` | `tenants:manage` | Reactivate |
| GET | `/tenants/{customer_id}/cascade-warning` | `tenants:manage` | Pre-delete impact: `{user_count, ticket_count, api_key_count, message}` |
| GET | `/tenants/{customer_id}/endpoints` | `tenants:read` | Per-tenant infra endpoint refs (`pg_dsn_ref`, `qdrant_url_ref`, `object_store_ref`) |
| PUT | `/tenants/{customer_id}/endpoints` | `tenants:manage` | Upsert endpoint refs |
| GET | `/tenants/{customer_id}/scopes` | `tenants:read` | List capability scopes (tool allowlists) |
| POST | `/tenants/{customer_id}/scopes` | `tenants:manage` | Create scope → 201 (`scope_name`, `allowed_tools[]`, `rate_limit?`) |
| PATCH | `/tenants/{customer_id}/scopes/{scope_id}` | `tenants:manage` | Update scope |
| DELETE | `/tenants/{customer_id}/scopes/{scope_id}` | `tenants:manage` | Delete scope → 204 |

`TenantCreate`: `{customer_id (slug [a-zA-Z0-9_-]+), name, plan="standard"}`. Tenant create/delete is synced to the MCP Gateway inventory (best-effort; see [Gateway Admin API](#gateway-admin-api) and [MCP Gateway architecture](../architecture/mcp_gateway.md)) — the create response carries `gateway_sync: {status: synced|error|skipped, ...}`.

### User-tenant assignments — `/api/v1/tenants/{customer_id}/users`

Source: `src/api/routers/assignments.py` (models inline). Links a user to a tenant with a profile.

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/tenants/{customer_id}/users` | `users:read` | List assignments (`AssignmentResponse[]` with user email/name and profile name) |
| POST | `/tenants/{customer_id}/users` | `users:manage` | Assign → 201 (`{user_id, profile_id}`) |
| PATCH | `/tenants/{customer_id}/users/{user_id}` | `users:manage` | Change the assignment's profile |
| DELETE | `/tenants/{customer_id}/users/{user_id}` | `users:manage` | Remove the user from the tenant → 204 |

### Inventory — `/api/v1/inventory`

Source: `src/api/routers/inventory.py`, schemas in `src/api/schemas/inventory.py`. Manages the tenant's logical inventory — the `ClientContext` the Engineer reads via `query_client_db`. Every endpoint uses `require_tenant_permission`: platform admins **must** target a tenant with `?customer_id=<tenant>` (otherwise 400 `tenant_required`).

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/inventory` | `inventory:read` | Overview counts (`InventoryOverview`) |
| GET | `/inventory/full` | `inventory:read` | Full context document |
| POST | `/inventory/import` | `inventory:write` | Bulk import — **replaces** the whole context |
| GET | `/inventory/components` | `inventory:read` | List components/devices |
| POST | `/inventory/components` | `inventory:write` | Create component → 201 (may sync a device to the gateway, see below) |
| GET | `/inventory/components/{component_id}` | `inventory:read` | Component detail |
| PATCH | `/inventory/components/{component_id}` | `inventory:write` | Update component |
| DELETE | `/inventory/components/{component_id}` | `inventory:write` | Delete component (also deletes its gateway device if managed) |
| GET | `/inventory/dependencies` | `inventory:read` | List dependencies (topology edges) |
| POST | `/inventory/dependencies` | `inventory:write` | Create dependency → 201 |
| DELETE | `/inventory/dependencies?source_id&target_id&relation` | `inventory:write` | Delete dependency (identified by query params) |
| GET | `/inventory/baselines` | `inventory:read` | List metric baselines |
| POST | `/inventory/baselines` | `inventory:write` | Create baseline → 201 |
| PATCH | `/inventory/baselines/{component_id}/{metric}` | `inventory:write` | Update baseline |
| DELETE | `/inventory/baselines/{component_id}/{metric}` | `inventory:write` | Delete baseline |
| GET | `/inventory/changes` | `inventory:read` | List known changes |
| POST | `/inventory/changes` | `inventory:write` | Record known change → 201 |
| PATCH | `/inventory/changes/{index}` | `inventory:write` | Update known change |
| DELETE | `/inventory/changes/{index}` | `inventory:write` | Delete known change |

**MCP managed devices** — `ComponentCreate`/`ComponentUpdate` accept an optional `mcp_connection` block that also registers the device in the MCP Gateway inventory:

```json
{
  "id": "fw_branch_2", "ref": "Branch 2 FortiGate", "role": "firewall",
  "mcp_connection": {
    "vendor": "fortinet", "appliance": "fortigate", "device_type": "fortios",
    "host": "10.0.2.1", "port": 443,
    "token": "<plaintext — write-only, encrypted and stored by the gateway>",
    "verify_ssl": false, "primary": false
  }
}
```

Valid `device_type` values come from the loaded gateway packs (`GET /admin/packs`): `fortios` (FortiGate, `token` = REST API key) and `fortiedr` (FortiEDR management server, `token` = `api_user@organization:password` for HTTP Basic auth).

- The component is saved locally first; the gateway outcome comes back as `gateway_sync` (`status`: `synced` | `error` | `skipped`) and is persisted in `metadata.mcp.sync`. The token is never stored or returned by the Platform API.
- `PATCH` with `"mcp_managed": false` detaches the device from the gateway.
- Requires `MCP_GATEWAY_ADMIN_URL` + `MCP_GATEWAY_ADMIN_TOKEN` in the app environment (otherwise `gateway_sync.status = "skipped"`).

---

## Legacy ingestion

Mounted on the live app for backward compatibility (`src/api/app.py:_mount_legacy_webhook`, tag `legacy`). **Prefer `POST /api/v1/tickets` with an API key** — the webhook authenticates with a bare `X-Customer-ID` header, entirely outside the RBAC system, so anyone who can reach the port can submit tickets as any tenant.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/webhook/{source_id}` | `X-Customer-ID` header (required) | Ingest a raw JSON payload → 202 `{status, message, ticket_id, job_id}` |
| GET | `/api/v1/jobs/{job_id}` | `X-Customer-ID` header (optional, tenant-scopes) | Job/run status (404 if unknown) |

`source_id` is any string used for traceability (e.g. `servicenow`, `jira`). The body is arbitrary JSON; `IngestionService` (`src/ingestion/service.py`) normalizes it into a `Ticket`: extracts text from `text` / `description` / `short_description`, maps source priority to `severity`, generates an id when absent, and preserves the raw payload for audit. Processing then follows the same background-run path as `POST /tickets`.

> `src/ingestion/api.py` is a separate standalone legacy FastAPI app with an overlapping webhook surface. It is **not** mounted by the platform app and is not a supported interface — do not build against it.

---

## Gateway Admin API

REST routes on the MCP Gateway (`mcp_gateway/gateway/admin_api.py`), mounted via `FastMCP.custom_route` — no MCP tools are added, so the tool-name freeze is unaffected. Manages the gateway's device inventory (`inventory/tenants/<cid>/`); device tokens are Fernet-encrypted by the gateway and never leave it.

**Normal consumers are automatic**: `TenantService` and `InventoryService` in the Platform API call these endpoints through `src/api/services/gateway_admin_client.py` on tenant create/delete and component sync. Manual calls are an operator tool — see the [Gateway Operations runbook](../operations/gateway_operations.md).

**Auth**: header `X-Admin-Token` compared (constant-time) against the `GATEWAY_ADMIN_TOKEN` env var. When the var is unset, every endpoint except `/admin/health` answers **503 `admin_disabled`** — the API is opt-in.

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/health` | Liveness + `admin_enabled` flag (**no auth**) |
| GET | `/admin/packs` | Discovered appliance packs: `{vendor, appliance, device_type, prefix}` |
| POST | `/admin/tenants` | Provision a tenant inventory dir + `tenant.yaml` → 201 (`TenantWrite`) |
| DELETE | `/admin/tenants/{cid}` | Remove a tenant's inventory tree (409 `manual_devices_present` while hand-maintained device files exist) |
| GET | `/admin/tenants/{cid}/devices` | All devices, manual + managed; tokens redacted as `***` |
| POST | `/admin/tenants/{cid}/devices` | Create managed device → 201 (`DeviceWrite`; 404 `unknown_tenant` if the tenant dir is missing) |
| PATCH | `/admin/tenants/{cid}/devices/{device_id}` | Partial update (`DevicePatch`); omitting `token` keeps the stored ciphertext |
| DELETE | `/admin/tenants/{cid}/devices/{device_id}` | Delete managed device |
| POST | `/admin/reload` | Re-read the inventory into all cached tenant registries |

**Models** (Pydantic, in `admin_api.py`):

- `TenantWrite`: `id` (slug `[a-zA-Z0-9_-]+` — becomes a directory name), `name`, `description?`
- `DeviceWrite`: `id`, `name`, `type` (must match a pack's `device_type`, else 422 `unknown_device_type`), `description?`, `tags[]`, `primary=false`, `connection`
- `ConnectionWrite`: `host`, `port=443`, `token?` (plaintext, **write-only**), `verify_ssl=false`
- `DevicePatch` / `ConnectionPatch`: all-optional variants

**Behavior**:

- Mutations hot-reload the tenant's cached routing slice; responses carry `"reloaded": bool` (false ⇒ tenant not cached yet — picked up lazily on its next request). Device create/update also return `"warnings"` (e.g. a hand-maintained primary outranking the managed one).
- The API only writes `devices/managed.yaml`; hand-maintained device files are readable but immutable through the API (409 `conflict`).
- Error codes: 409 `conflict` / `tenant_exists` / `manual_devices_present`, 404 `not_found` / `unknown_tenant`, 422 `validation_error` / `unknown_device_type` / `invalid_tenant_id`, 503 `admin_disabled` / `encryption_unavailable`.

**SSE endpoint** — `/sse/` is the MCP transport the Engineer (and other MCP clients) connect to. It is **unauthenticated**: anyone who can reach the port can execute all tools and spoof the per-request `tenant` header. Cross-tenant isolation depends on the network boundary until SSE auth exists — expose it only on trusted networks (see [MCP Gateway architecture](../architecture/mcp_gateway.md), Future work).

---

## See also

- [Quickstart](../setup/quickstart.md) — run the API server end to end
- [API Keys & Users runbook](../operations/api_keys_and_users.md) — admin bootstrap, CLI key minting, JWT workflows
- [Ticket Operations runbook](../operations/ticket_operations.md) — submit/follow/triage walkthrough
- [Gateway Operations runbook](../operations/gateway_operations.md) — gateway run modes, device onboarding
- [MCP Gateway architecture](../architecture/mcp_gateway.md) — packs, name-freeze, inventory model, secrets
- [Deployment](../setup/deployment.md) — Docker Compose production setup
