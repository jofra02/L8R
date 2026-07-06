# MCP Gateway

`mcp_gateway/` is the platform's tool-execution service: a **generic OpenAPI/Swagger → MCP gateway**. It converts vendor API specifications into MCP tools at startup and exposes them over SSE. The Engineer agent consumes it like any other MCP server (`data/mcp/servers.yaml`); other MCP clients (n8n, Claude Desktop via stdio) can consume it too.

It originated as the standalone `fortinet_ai_suite` repository and was merged here as a first-class component. The old repo is archived (branch `archive/final-state`, tag `archive/pre-merge-2026-07-06`).

```
Ticket → Engineer agent → execute_tool ──SSE──> mcp-gateway ──HTTPS──> FortiGate / appliance
                                                    │
                                       vendors/<pack>/specs/*.json
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
│   ├── vendor_pack.py      # manifest.yaml loading + hooks.py discovery
│   ├── spec_pipeline.py    # OpenAPI → FastMCP build pipeline (order is frozen)
│   ├── schema_fixes.py     # Generic spec fixes + operationId sanitizer
│   ├── routing_client.py   # Multi-device httpx client ('device' header routing)
│   ├── auth.py             # AuthStrategy registry (bearer_header today)
│   ├── config.py           # ACTIVE_CUSTOMER_ID, DeviceRegistry (primary flag)
│   ├── middleware.py       # Tracing + optional Prometheus histogram
│   ├── inventory/          # Tenant/device YAML registry + Fernet secrets
│   └── tests/test_name_freeze.py
├── vendors/
│   └── fortinet/           # First vendor pack
│       ├── manifest.yaml   # prefix fgt, auth, glob, name rules
│       ├── hooks.py        # SD-WAN monolith split + filter syntax help
│       └── specs/{cmdb,monitor,log}/  # 62 FortiOS OpenAPI specs (~25 MB)
├── inventory/              # GITIGNORED except *.example.yaml
│   └── tenants/<customer_id>/devices/*.yaml
└── scripts/                # dump_tools.py, encrypt_secret.py, rotate_master_key.py
```

## Vendor pack contract

A vendor pack is a directory under `vendors/` — **adding a vendor requires no engine code**:

1. `mkdir vendors/<vendor>/specs/<group>/` and drop OpenAPI/Swagger JSON files in. Each `<group>` directory becomes a sub-server (e.g. `cmdb`, `monitor`).
2. Write `vendors/<vendor>/manifest.yaml`:

```yaml
name: acme                    # slug (defaults to the directory name)
display_name: Acme Firewall   # server display name
prefix: acme                  # first token of every tool name
device_type: acme_fw          # inventory devices served by this pack
auth: bearer_header           # strategy from gateway/auth.py
spec_glob: "*.json"           # spec files inside each group dir
name_strips: []               # substrings stripped from spec filenames
sanitizer_stopwords: []       # filler tokens the name sanitizer may drop
inventory_tool: true          # expose <prefix>_get_inventory_tree
device_param_description: "Optional: target device name. Defaults to primary."
```

3. Optional `hooks.py` for vendor-specific transforms:
   - `SPEC_FIXES: list[callable]` — run per spec after the generic fixes (see `vendors/fortinet/hooks.py:fix_sdwan_monolith`).
   - `PARAMETER_DOC_APPENDS: dict[param_name, help_text]` — appended to matching parameter descriptions (e.g. FortiOS `filter` syntax help).
4. Add devices of that `device_type` to `inventory/tenants/<customer_id>/devices/` (see `firewalls.example.yaml`).
5. If the vendor slug isn't recognized by `src/core/registry.py:_VENDOR_PATTERNS`, tag the server with `vendor:` in `data/mcp/servers.yaml`.

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
- Every generated tool has an optional `device` header parameter. `RoutingClient.send()` looks the id up in the `DeviceRegistry`, rewrites the URL host/port and swaps the auth headers per the pack's `AuthStrategy`. Without the header, the **primary** device is used (`primary: true` in YAML, else the first device loaded).
- `fgt_get_inventory_tree` lists valid device ids for the agent.

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

## Future work

- **SSE authentication**: the endpoint is currently unauthenticated — anyone who can reach the port can execute all tools. Acceptable only on trusted networks; add a bearer/API-key check before exposing beyond the compose network.
- Second vendor pack (FortiAnalyzer or another appliance) to exercise the multi-pack path.
- Optional pagination/filtering of the tool listing for clients that can't handle ~2.5k tools.
