# MCP Gateway

`mcp_gateway/` is the platform's tool-execution service: a **generic OpenAPI/Swagger → MCP gateway**. It converts vendor API specifications into MCP tools at startup and exposes them over SSE. The Engineer agent consumes it like any other MCP server (`data/mcp/servers.yaml`); other MCP clients (n8n, Claude Desktop via stdio) can consume it too.

It originated as the standalone `fortinet_ai_suite` repository and was merged here as a first-class component. The old repo is archived (branch `archive/final-state`, tag `archive/pre-merge-2026-07-06`).

```
Ticket → Engineer agent → execute_tool ──SSE──> mcp-gateway ──HTTPS──> FortiGate / appliance
                                                    │
                                       vendors/<vendor>/<appliance>/specs/*.json
                                       inventory/tenants/<customer_id>/devices/*.yaml
```

## Layout

```
mcp_gateway/
├── main.py                 # Entry point — env-driven (SERVER_TRANSPORT: sse|stdio)
├── pyproject.toml          # Own uv project; fastmcp PINNED (see name-freeze)
├── Dockerfile              # compose service `mcp-gateway`
├── baseline_tools.txt      # Frozen tool-name set (2546 names) — test fixture
├── gateway/                # Vendor-agnostic engine
│   ├── app.py              # build_gateway(): discovers packs, mounts, exposes /sse/
│   ├── admin_api.py        # Inventory admin REST API (/admin/*, X-Admin-Token)
│   ├── vendor_pack.py      # manifest.yaml loading + hooks.py discovery
│   ├── spec_pipeline.py    # OpenAPI → FastMCP build pipeline (order is frozen)
│   ├── schema_fixes.py     # Generic spec fixes + operationId sanitizer
│   ├── routing_client.py   # Multi-device httpx client ('device' header routing)
│   ├── auth.py             # AuthStrategy registry (bearer_header today)
│   ├── config.py           # ACTIVE_CUSTOMER_ID, DeviceRegistry (reload(), primary flag)
│   ├── middleware.py       # Tracing + optional Prometheus histogram
│   ├── inventory/          # Tenant/device YAML registry + Fernet secrets + managed.yaml store
│   └── tests/              # test_name_freeze.py, test_admin_api.py, test_routing_reload.py
├── vendors/                # vendors/<vendor>/<appliance>/ — one pack per product
│   └── fortinet/           # Vendor (manufacturer)
│       └── fortigate/      # Appliance pack (fortianalyzer, fortimanager... go next to it)
│           ├── manifest.yaml   # prefix fgt, auth, glob, name rules
│           ├── hooks.py        # SD-WAN monolith split + filter syntax help
│           └── specs/{cmdb,monitor,log}/  # 62 FortiOS OpenAPI specs (~25 MB)
├── inventory/              # GITIGNORED except *.example.yaml
│   └── tenants/<customer_id>/devices/*.yaml
└── scripts/                # dump_tools.py, encrypt_secret.py, rotate_master_key.py
```

## Appliance pack contract

Packs live at `vendors/<vendor>/<appliance>/` — the **vendor** is the manufacturer (fortinet, cisco, paloalto) and each of its **appliances/products** (fortigate, fortianalyzer, ios_xe, panos, ...) is a self-contained pack. This keeps one vendor's multiple product lines separate: each appliance has its own API family, prefix, auth style and device type. **Adding a pack requires no engine code**:

1. `mkdir -p vendors/<vendor>/<appliance>/specs/<group>/` and drop OpenAPI/Swagger JSON files in. Each `<group>` directory becomes a sub-server (e.g. `cmdb`, `monitor`).
2. Write `vendors/<vendor>/<appliance>/manifest.yaml`:

```yaml
vendor: acme                  # manufacturer slug (defaults to the parent directory name)
name: firewall_x              # appliance slug (defaults to the directory name)
display_name: Acme Firewall X # server display name
prefix: acmefw                # first token of every tool name
device_type: acme_fw          # inventory devices served by this pack
auth: bearer_header           # strategy from gateway/auth.py
spec_glob: "*.json"           # spec files inside each group dir
name_strips: []               # substrings stripped from spec filenames
sanitizer_stopwords: []       # filler tokens the name sanitizer may drop
inventory_tool: true          # expose <prefix>_get_inventory_tree
device_param_description: "Optional: target device name. Defaults to primary."
```

3. Optional `hooks.py` for appliance-specific transforms:
   - `SPEC_FIXES: list[callable]` — run per spec after the generic fixes (see `vendors/fortinet/fortigate/hooks.py:fix_sdwan_monolith`).
   - `PARAMETER_DOC_APPENDS: dict[param_name, help_text]` — appended to matching parameter descriptions (e.g. FortiOS `filter` syntax help).
4. Add devices of that `device_type` to `inventory/tenants/<customer_id>/devices/` (see `firewalls.example.yaml`).
5. If the vendor slug isn't recognized by `src/core/registry.py:_VENDOR_PATTERNS`, tag the server with `vendor:` in `data/mcp/servers.yaml`.

Each pack mounts at its own `prefix`, so prefixes must be unique across packs (e.g. `fgt` for FortiGate, `faz` for a future FortiAnalyzer pack).

Tool names follow the mount chain: `{prefix}_{group}_{spec_mount_name}_{operationId}`.

## Name-freeze contract (IMPORTANT)

The Qdrant `tool_catalog` collection indexes tools **by name** and enriches them with LLM-classified metadata (an expensive batch job). Renaming tools invalidates the index. Names must therefore stay stable across releases. Three things pin them:

1. **`fastmcp` is pinned exactly** (`==2.14.5` in `mcp_gateway/pyproject.toml`) because `FastMCP.from_openapi` drives tool naming.
2. **The pipeline order in `spec_pipeline.py` is frozen**: fixes → sanitize → basePath → device-header injection → param doc appends → `from_openapi` → mount.
3. **The sanitizer's 64-char budget quirk is intentional**: `sanitize_operation_ids` computes the budget against the spec-level mount name only, not the full chain, so ~470 final names exceed 64 chars. Do not "fix" this — it renames every hash-truncated tool.

Guard: `gateway/tests/test_name_freeze.py` builds the gateway offline and asserts the name set equals `baseline_tools.txt` (2546 names captured from the original server).

**If you intentionally change names** (new specs, fastmcp upgrade): run the test, regenerate the baseline with `scripts/dump_tools.py --out baseline_tools.txt`, then re-index in support_ai_agent (delete/recreate the `tool_catalog` collection and restart the app so `CapabilityRegistry.index_tools()` re-runs, including the LLM classification batches).

## Tenants, inventory and multi-device routing

- The gateway serves **one tenant per process**: `ACTIVE_CUSTOMER_ID` (default `fake_client`). Tenant ids match the `customer_id` used across support_ai_agent — the device ids in `mcp_gateway/inventory/tenants/fake_client/devices/` are the same ones `query_client_db` returns from `data/tenants/fake_client/context.yaml`.
- Every generated tool has an optional `device` header parameter. `RoutingClient.send()` resolves the target against the **live** `DeviceRegistry` on every request (header id, else the current **primary**: `primary: true` in YAML, else the first device loaded), rewrites the URL host/port and swaps the auth headers per the pack's `AuthStrategy`. Because resolution is per-request, admin-API hot reloads — including a primary change — take effect without a restart; the constructor's base_url only remains as the empty-registry fallback.
- `fgt_get_inventory_tree` lists valid device ids for the agent.
- The inventory root defaults to `mcp_gateway/inventory` and can be overridden with `INVENTORY_ROOT` (compose sets `/app/inventory`; the volume is mounted read-write so the admin API can persist).

## Inventory admin API

`gateway/admin_api.py` mounts REST routes on the same server (via `FastMCP.custom_route` — **no MCP tools are added**, so the name-freeze is unaffected). The support_ai_agent platform calls it when a user manages devices from the frontend inventory UI; tokens are encrypted (Fernet) and persisted by the gateway, so **appliance credentials never leave this process**.

| Endpoint | Purpose |
|---|---|
| `GET /admin/health` | Liveness + `admin_enabled` flag (no auth) |
| `GET /admin/packs` | Discovered packs: vendor/appliance/device_type/prefix |
| `POST /admin/tenants` | Provision a tenant: `inventory/tenants/<id>/` + `tenant.yaml` + `devices/` |
| `DELETE /admin/tenants/{cid}` | Remove a tenant's inventory tree (409 if hand-maintained device files exist) |
| `GET /admin/tenants/{cid}/devices` | All devices (managed + hand-maintained), tokens redacted |
| `POST /admin/tenants/{cid}/devices` | Create a managed device (plaintext token in body → stored as `ENC(...)`) |
| `PATCH /admin/tenants/{cid}/devices/{id}` | Partial update; token omitted ⇒ existing ciphertext kept byte-identical |
| `DELETE /admin/tenants/{cid}/devices/{id}` | Remove a managed device |
| `POST /admin/reload` | Force re-read of the inventory into all registries |

Rules:

- **Auth**: `X-Admin-Token` header must equal the `GATEWAY_ADMIN_TOKEN` env var. Unset var ⇒ every admin endpoint answers 503 (opt-in API).
- **managed.yaml**: the API only ever writes `devices/managed.yaml` (atomic write via temp file + rename, header comment marks it machine-owned). Hand-maintained files are readable but immutable through the API (409) — their comments/formatting are never touched.
- **Single primary**: marking a managed device `primary: true` clears the flag on other managed devices of the same type. If a hand-maintained device of that type is also primary it **wins** (file order) and the response carries a warning.
- **Hot reload**: after a successful mutation for the active tenant, all `DeviceRegistry` instances `reload()` — new/changed/removed devices are routable immediately (`"reloaded": true` in the response). Mutations for other tenants only write files (`"reloaded": false`).
- **Validation**: `type` must match a discovered pack's `device_type`; duplicate ids conflict (409). Device creation requires the tenant's `inventory/tenants/<cid>/` directory to already exist — an unknown `cid` answers 404 `unknown_tenant` instead of silently minting a new tenant directory. Tenant ids are slug-validated (`[a-zA-Z0-9_-]+`) because they become directory names.
- **Tenant lifecycle**: `POST /admin/tenants` writes a minimal `tenant.yaml` (adopting a bare pre-created directory); duplicate ⇒ 409 `tenant_exists`. `DELETE /admin/tenants/{cid}` removes the whole tenant tree, but **refuses (409 `manual_devices_present`)** while hand-maintained device files exist — the API never deletes operator-managed config. Deleting the active tenant reloads the registries to empty.

App-side flow: `InventoryService` (platform API) calls the admin API through `src/api/services/gateway_admin_client.py` when a Component carries an `mcp_connection` block. The component is persisted locally **first** (sync status `pending`), then synced to the gateway, and the outcome is recorded in `Component.metadata["mcp"]["sync"]` and returned as `gateway_sync` (the token is write-only and never persisted app-side) — the gateway never holds a device the app has no record of.

Tenant lifecycle is synced the same way: `TenantService.create_tenant` provisions the gateway inventory **after** the local commit (best-effort; outcome returned as `gateway_sync` in `POST /tenants`), and `TenantService.delete_tenant` removes it before the local delete (best-effort; a `manual_devices_present` conflict is logged and requires operator cleanup on the gateway host). Both are idempotent: a create retry treats gateway 409 as synced, a delete retry treats 404 as synced. The `register-tenant` CLI (`seed_tenant`) provisions the gateway too when `MCP_GATEWAY_ADMIN_URL`/`MCP_GATEWAY_ADMIN_TOKEN` are configured.

Drift self-heal: when a device create hits 404 `unknown_tenant` (tenant created before the sync feature, or while the gateway was down), `GatewayAdminClient.upsert_device` auto-provisions the tenant via `POST /admin/tenants` and retries the device create once — device CRUD from the app never requires out-of-band provisioning. App-side, tenant deletion cascades at the DB level: every FK to `platform_tenants` carries `ON DELETE CASCADE` (migration `d5e6f7a8b9c0`), so `DELETE /tenants/{cid}?force=true` removes all tenant rows (contexts, scopes, endpoints, keys, profile assignments, tickets and their children).

## Secrets

- Device tokens are stored as `ENC(...)` (Fernet), decrypted in memory with `INVENTORY_MASTER_KEY`.
- Live inventory files and `.env` are **gitignored**; only `*.example.yaml` ships in git.
- Encrypt a token: `uv run python scripts/encrypt_secret.py "<token>"`. Generate a key: `--generate`.

### Key rotation runbook

1. `uv run python scripts/encrypt_secret.py --generate` → new key.
2. `uv run python scripts/rotate_master_key.py --old-key <OLD> --new-key <NEW> --dry-run`, then without `--dry-run`.
3. Update `INVENTORY_MASTER_KEY` in `mcp_gateway/.env` and the compose environment; restart the gateway.
4. Because the pre-merge history of the old `fortinet_ai_suite` repo contains the encrypted device file, also **regenerate the API tokens on the FortiGates themselves** and re-encrypt them (step: FortiOS → System → API admin → regenerate; then `encrypt_secret.py` and paste into the YAML).

## Running

| Mode | Command | URL |
|---|---|---|
| Compose (with the whole stack) | `docker compose up -d mcp-gateway` | `http://localhost:${MCP_GATEWAY_PORT:-8001}/sse/` (in-network: `http://mcp-gateway:8000/sse`) |
| Host dev | `cd mcp_gateway && uv run python main.py` | `http://localhost:8001/sse/` (per `mcp_gateway/.env`) |
| stdio | `SERVER_TRANSPORT=stdio uv run python main.py` | — |

The agent's `data/mcp/servers.yaml` points at `${MCP_GATEWAY_URL:-http://localhost:8001/sse}`; compose sets `MCP_GATEWAY_URL` on the `app` service.

Verification: `uv run pytest gateway/tests/` (offline name freeze) and `uv run python scripts/dump_tools.py --url http://localhost:8001/sse/ --out live.txt && diff baseline_tools.txt live.txt` (live).

Operational procedures: [Gateway Operations](../operations/gateway_operations.md) · [Gateway Secrets](../operations/gateway_secrets.md) (token encryption, key rotation) · [Gateway Upgrades](../operations/gateway_upgrades.md) (add a pack, bump fastmcp).

## Future work

- **SSE authentication**: the endpoint is currently unauthenticated — anyone who can reach the port can execute all tools. Acceptable only on trusted networks; add a bearer/API-key check before exposing beyond the compose network.
- Second appliance pack (`vendors/fortinet/fortianalyzer/` or another vendor's product) to exercise the multi-pack path.
- Optional pagination/filtering of the tool listing for clients that can't handle ~2.5k tools.
