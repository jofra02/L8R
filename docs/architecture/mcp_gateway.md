# MCP Gateway

`mcp_gateway/` is the platform's tool-execution service: a **generic OpenAPI/Swagger → MCP gateway**. It converts vendor API specifications into MCP tools at startup and exposes them over SSE. The Engineer agent consumes it like any other MCP server (`data/mcp/servers.yaml`); other MCP clients (n8n, Claude Desktop via stdio) can consume it too.

It originated as the standalone `fortinet_ai_suite` repository and was merged here as a first-class component. The old repo is archived (branch `archive/final-state`, tag `archive/pre-merge-2026-07-06`).

```
Ticket → Engineer agent → execute_tool ──SSE──> mcp-gateway ──HTTPS──> FortiGate / appliance
                                                    │
                                       vendors/<vendor>/<appliance>/<version>/specs/*.json
                                       inventory/tenants/<customer_id>/devices/*.yaml
```

## Layout

```
mcp_gateway/
├── main.py                 # Entry point — env-driven (SERVER_TRANSPORT: sse|stdio)
├── pyproject.toml          # Own uv project; fastmcp PINNED (see name-freeze)
├── Dockerfile              # compose service `mcp-gateway`
├── baseline_tools.txt      # Frozen tool-name set (2776 names) — test fixture
├── gateway/                # Vendor-agnostic engine
│   ├── app.py              # build_gateway(): discovers packs, mounts, exposes /sse/
│   ├── admin_api.py        # Inventory admin REST API (/admin/*, X-Admin-Token)
│   ├── vendor_pack.py      # manifest.yaml loading + hooks.py discovery
│   ├── spec_pipeline.py    # OpenAPI → FastMCP build pipeline (order is frozen)
│   ├── schema_fixes.py     # Generic spec fixes + operationId sanitizer
│   ├── routing_client.py   # Multi-device httpx client ('device' header routing)
│   ├── auth.py             # AuthStrategy registry (bearer_header, basic_header)
│   ├── config.py           # DEFAULT_TENANT, DeviceRegistry + TenantRegistries (lazy per-tenant, reload(), primary flag)
│   ├── middleware.py       # Tracing + optional Prometheus histogram
│   ├── inventory/          # Tenant/device YAML registry + Fernet secrets + managed.yaml store
│   └── tests/              # test_name_freeze.py, test_admin_api.py, test_routing_reload.py, test_fortiedr_pack.py, test_versioned_packs.py
├── vendors/                # vendors/<vendor>/<appliance>/<version>/ — one pack per product version
│   └── fortinet/           # Vendor (manufacturer)
│       ├── fortigate/      # Appliance (fortianalyzer, fortimanager... go next to it)
│       │   └── 7.4/        # Pack version — FortiOS 7.4 (7.6 would mount alongside as fgt76)
│       │       ├── manifest.yaml   # prefix fgt74, version "7.4", auth bearer_header
│       │       ├── hooks.py        # SD-WAN monolith split + filter syntax help
│       │       └── specs/{cmdb,monitor,log}/  # 62 FortiOS OpenAPI specs (~25 MB)
│       └── fortiedr/       # FortiEDR (generated — see FortiEDR/ + converter)
│           └── 6.2/        # Pack version — FortiEDR 6.2
│               ├── manifest.yaml   # prefix fedr62, version "6.2", auth basic_header
│               └── specs/mgmt/     # 26 OpenAPI 3.0.3 specs (229 operations)
├── FortiEDR/swagger/v6.2/  # Raw FortiEDR Swagger 2.0 exports (converter source of truth)
├── inventory/              # GITIGNORED except *.example.yaml
│   └── tenants/<customer_id>/devices/*.yaml
└── scripts/                # dump_tools.py, convert_fortiedr_specs.py, encrypt_secret.py, rotate_master_key.py
```

## Appliance pack contract

Packs live at `vendors/<vendor>/<appliance>/<version>/` — the **vendor** is the manufacturer (fortinet, cisco, paloalto), each of its **appliances/products** (fortigate, fortianalyzer, ios_xe, panos, ...) can ship several **firmware/OS versions**, and each version is a self-contained pack. Multiple versions of the same appliance mount concurrently: they share the `device_type` (same tenant inventory) but each carries its own versioned tool prefix (`fgt74`, `fgt76`, ...), so tool names never collide and the app can scope tool searches to the version each device actually runs. **Adding a pack requires no engine code**:

1. `mkdir -p vendors/<vendor>/<appliance>/<version>/specs/<group>/` and drop OpenAPI/Swagger JSON files in. Each `<group>` directory becomes a sub-server (e.g. `cmdb`, `monitor`).
2. Write `vendors/<vendor>/<appliance>/<version>/manifest.yaml`:

```yaml
vendor: acme                  # manufacturer slug (defaults to the grandparent directory name)
name: firewall_x              # appliance slug (defaults to the parent directory name)
version: "3.1"                # firmware/OS version (defaults to the directory name; quote it)
display_name: Acme Firewall X # server display name
prefix: acmefw31              # first token of every tool name — include the version
device_type: acme_fw          # inventory devices served by this pack (NOT versioned)
auth: bearer_header           # strategy from gateway/auth.py
spec_glob: "*.json"           # spec files inside each group dir
name_strips: []               # substrings stripped from spec filenames
sanitizer_stopwords: []       # filler tokens the name sanitizer may drop
inventory_tool: true          # expose <prefix>_get_inventory_tree
device_param_description: "Optional: target device name. Defaults to primary."
```

3. Optional `hooks.py` for appliance-specific transforms:
   - `SPEC_FIXES: list[callable]` — run per spec after the generic fixes (see `vendors/fortinet/fortigate/7.4/hooks.py:fix_sdwan_monolith`).
   - `PARAMETER_DOC_APPENDS: dict[param_name, help_text]` — appended to matching parameter descriptions (e.g. FortiOS `filter` syntax help).
4. Add devices of that `device_type` to `inventory/tenants/<customer_id>/devices/` (see `firewalls.example.yaml`). Devices carry an optional `os_version` ("7.4.5") used app-side to match them to the right pack version.
5. If the vendor slug isn't recognized by `src/core/registry.py:_VENDOR_PATTERNS`, tag the server with `vendor:` in `data/mcp/servers.yaml`.

Each pack mounts at its own `prefix`, so prefixes must be unique across packs — `build_gateway` fails fast on duplicates (e.g. `fgt74` for FortiOS 7.4, `fedr62` for FortiEDR 6.2, `faz74` for a future FortiAnalyzer pack). `GET /admin/packs` exposes the mounted packs' identity (`vendor`, `appliance`, `version`, `prefix`, `device_type`, `pack_key = vendor/appliance/version`); `CapabilityRegistry` in the app consumes it to tag every catalog entry with its pack identity (see [Tool Catalog](../operations/tool_catalog.md)).

Tool names follow the mount chain: `{prefix}_{group}_{spec_mount_name}_{operationId}`.

### FortiEDR pack (second reference implementation)

`vendors/fortinet/fortiedr/6.2/` serves FortiEDR 6.2 management servers (`device_type: fortiedr`, prefix `fedr62`, HTTP Basic auth via the `basic_header` strategy — the device `connection.token` holds `organization\api_user:password` — FortiEDR multi-tenancy format with the org as a backslash prefix, e.g. `Acme\apiuser:secret`; the API user needs the REST API role, and the `user@organization` form is rejected with 401 — Fernet-encrypted like any token. Basic is sent on every call because FortiEDR's `X-Auth-Token` is bound to the TCP session). Its specs are **generated**: the raw Springfox Swagger 2.0 exports live in `FortiEDR/swagger/v6.2/` and `scripts/convert_fortiedr_specs.py` converts them to OpenAPI 3.0.3 into `6.2/specs/mgmt/` — edit the converter, never the generated specs (`--check` verifies drift). The converter also rewrites operationIds deterministically from `(method, path)` with two safety invariants: every GET name carries a `_get` token (read-only marker used by `src/core/mcp_executor.py`), and every mutating operation's name contains a blocked safety keyword so the app-side name filter hides it — except five reviewed read-only POSTs (`READ_EXEMPT`: threat-hunting search/counts/facets, dashboard/incidents generate-report). Contract pinned by `gateway/tests/test_fortiedr_pack.py`.

The converter is also the pack's **spec-curation layer** (the FortiEDR analogue of the FortiGate pack's `hooks.py` `SPEC_FIXES` — curation is baked into the checked-in specs instead of applied at mount time, so it is diffable and drift-guarded): `QUERY_PARAM_ENRICHMENTS` overrides query-parameter schemas and descriptions where the raw Springfox export contradicts or under-documents the live API. Current entries (all live-verified 2026-07-23): `timeFilter` (enum shipped as two partial variants but live-verified as one shared 8-value parser), `startDate`/`endDate` (epoch **milliseconds** — epoch seconds are silently read as 1970 and return empty results, date strings 400), `organizationId` (omit for org-scoped credentials; where required, use the `accountId` from incident list/detail responses), and `device` (an entity-name FILTER, not the routing param — it collides with the platform's routing param name so the routing header is never injected on those operations, and a caller passing the platform component id gets HTTP 200 with zero results silently; verified: `device=fortiedr-01` → 0, real collector hostname → matches, omitted → full set). Enrichment descriptions **replace** the raw ones (the curation layer is authoritative). Entries touch only param schema/description — never operationIds — so they are name-freeze safe, and every entry must be live-verified (guarded by `test_enrichment_keys_are_live_verified`). A second curation table, `AREA_DESCRIPTION_NOTES`, appends a note to every operation description of an area (spec file) — currently `mobile` and `mobile_inventory`, whose raw descriptions ("Get incidents") read as drop-in alternatives to the main endpoints while every path in those areas answers HTTP 404 on consoles without the mobile protection module (live-verified 2026-07-23; guarded by `test_area_notes_are_live_verified`).

**The gateway never validates appliance responses.** `schema_fixes.apply_fixes` strips response body schemas from every spec before `FastMCP.from_openapi` (`_strip_response_content`, last step so vendor hooks see the full spec), so no OpenAPI-derived tool advertises an MCP output schema. Rationale: the gateway is a read-only evidence proxy — responses must reach the caller verbatim. Vendor response schemas mis-declare reality (Springfox omits nullability), and FastMCP's output validation discards a valid 200 payload whole on the first mismatch (observed live: FortiEDR `/api/incidents` returned 200 with data and the agent received only `Output validation error: None is not of type 'integer'`). The platform consumes text content only, so output schemas add nothing. Guarded end-to-end by `gateway/tests/test_schema_fixes.py`.

## Name-freeze contract (IMPORTANT)

The Qdrant `tool_catalog` collection indexes tools **by name** and enriches them with LLM-classified metadata (an expensive batch job). Renaming tools invalidates the index. Names must therefore stay stable across releases. Three things pin them:

1. **`fastmcp` is pinned exactly** (`==2.14.5` in `mcp_gateway/pyproject.toml`) because `FastMCP.from_openapi` drives tool naming.
2. **The pipeline order in `spec_pipeline.py` is frozen**: fixes → sanitize → basePath → device-header injection → param doc appends → `from_openapi` → mount.
3. **The sanitizer's 64-char budget quirk is intentional**: `sanitize_operation_ids` computes the budget against the spec-level mount name only, not the full chain, so ~470 final names exceed 64 chars. Do not "fix" this — it renames every hash-truncated tool.

Guard: `gateway/tests/test_name_freeze.py` builds the gateway offline and asserts the name set equals `baseline_tools.txt` (2776 names: 2546 `fgt74_*` captured from the original server + 230 `fedr62_*` added with the FortiEDR pack; prefixes carry the pack version since the versioned-pack layout).

**If you intentionally change names** (new specs, fastmcp upgrade): run the test, regenerate the baseline with `scripts/dump_tools.py --out baseline_tools.txt`, then re-index in support_ai_agent (delete/recreate the `tool_catalog` collection and restart the app so `CapabilityRegistry.index_tools()` re-runs, including the LLM classification batches).

## Tenants, inventory and multi-device routing

- The gateway is **multi-tenant**: routing resolves `(tenant, device)` per request. Tenant ids match the `customer_id` used across support_ai_agent — the device ids in `mcp_gateway/inventory/tenants/<cid>/devices/` are the same ones `query_client_db` returns from that tenant's `context.yaml`.
- Every generated tool has optional `tenant` and `device` header parameters. `RoutingClient.send()` resolves the tenant first (header, else the optional `DEFAULT_TENANT` fallback) into that tenant's lazily-built, **live** `DeviceRegistry`, then the device within it (header id, else the tenant's **primary**: `primary: true` in YAML, else the first device loaded), rewrites the URL host/port and swaps the auth headers per the pack's `AuthStrategy`. The `tenant` header is **framework-injected by the app** from the run's `customer_id` (never LLM-supplied); the LLM still supplies `device`. Because resolution is per-request, admin-API hot reloads — including a primary change — take effect without a restart; the constructor's base_url only remains as the no-route fallback. Multiple tenants are routable concurrently in one process — there is no active-tenant setting.
- Before routing, `send()` **drops blank query parameters** (`name=`). FastMCP's OpenAPI layer serializes unset optional query params as empty strings, and the Fortinet REST APIs reject blanks instead of applying their defaults (FortiEDR: HTTP 400 `Invalid value []` on enum filters, server-side SQL errors on blank numeric params). Dropping a blank is semantics-preserving for query params (blank ≡ absent → the appliance applies its own default); this is engine-level cleanup of an engine-generated artifact, not a vendor quirk, so it lives in `RoutingClient` rather than a pack hook. Tested in `gateway/tests/test_routing_client.py`.
- `TenantRegistries` (one per device_type) is a lazy cache of per-tenant `DeviceRegistry` objects; device ids stay unique only within a tenant, so each tenant keeps its own flat registry.
- `fgt74_get_inventory_tree` / `fedr62_get_inventory_tree` list valid device ids for the agent (per device_type).
- The inventory root defaults to `mcp_gateway/inventory` and can be overridden with `INVENTORY_ROOT` (compose sets `/app/inventory`; the volume is mounted read-write so the admin API can persist).

## Inventory admin API

`gateway/admin_api.py` mounts REST routes on the same server (via `FastMCP.custom_route` — **no MCP tools are added**, so the name-freeze is unaffected). The support_ai_agent platform calls it when a user manages devices from the frontend inventory UI; tokens are encrypted (Fernet) and persisted by the gateway, so **appliance credentials never leave this process**.

The endpoint contract (routes, `X-Admin-Token` auth, request models, error codes, hot-reload semantics) is documented in the [API Reference — Gateway Admin API](../integrations/api_reference.md#gateway-admin-api). Design rules specific to this component:

- **managed.yaml**: the API only ever writes `devices/managed.yaml` (atomic write via temp file + rename, header comment marks it machine-owned). Hand-maintained files are readable but immutable through the API — their comments/formatting are never touched.
- **Single primary**: marking a managed device `primary: true` clears the flag on other managed devices of the same type. If a hand-maintained device of that type is also primary it **wins** (file order) and the response carries a warning.
- **Tenant lifecycle**: `POST /admin/tenants` writes a minimal `tenant.yaml` (adopting a bare pre-created directory). `DELETE /admin/tenants/{cid}` removes the whole tenant tree, but refuses while hand-maintained device files exist — the API never deletes operator-managed config. Deleting a cached tenant reloads its slice to empty.

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

- **SSE authentication**: the endpoint is currently unauthenticated — anyone who can reach the port can execute all tools. Acceptable only on trusted networks; add a bearer/API-key check before exposing beyond the compose network. This also means the per-request `tenant` header is **spoofable** by anything that can reach the port — cross-tenant isolation depends on the network boundary until SSE auth exists.
- Second appliance pack (`vendors/fortinet/fortianalyzer/` or another vendor's product) to exercise the multi-pack path.
- Optional pagination/filtering of the tool listing for clients that can't handle ~2.5k tools.
