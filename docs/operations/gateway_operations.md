# Gateway Operations

> Run the MCP Gateway, verify the tool-name freeze, and manage device inventory.

The gateway is its own uv project at `mcp_gateway/`. Architecture: [mcp_gateway.md](../architecture/mcp_gateway.md).

## Run modes

| Mode | Command | Endpoint |
|---|---|---|
| Compose (normal) | `docker compose up -d mcp-gateway` | `http://localhost:${MCP_GATEWAY_PORT:-8001}/sse/` |
| Host dev | `cd mcp_gateway && uv sync && uv run python main.py` | port from `mcp_gateway/.env` (`SERVER_PORT`) |
| stdio (Claude Desktop etc.) | `SERVER_TRANSPORT=stdio uv run python main.py` | stdio |

All configuration is env-driven (no CLI flags): `ACTIVE_CUSTOMER_ID`, `INVENTORY_MASTER_KEY`, `INVENTORY_ROOT`, `GATEWAY_ADMIN_TOKEN`, `SERVER_HOST/PORT/TRANSPORT`, `LOG_LEVEL`, `GATEWAY_HTTP_TIMEOUT`.

> The SSE endpoint has **no authentication** (planned future work) — expose it only on trusted networks / the compose network. The `/admin/*` inventory API is authenticated via `X-Admin-Token` (`GATEWAY_ADMIN_TOKEN`); when the env var is unset it answers 503.

## Dump the tool list

```bash
cd mcp_gateway
uv run python scripts/dump_tools.py --out offline.txt                             # offline build
uv run python scripts/dump_tools.py --url http://localhost:8001/sse/ --out live.txt   # from a running server
```

## Verify the name-freeze

Tool names must stay byte-identical to `mcp_gateway/baseline_tools.txt` (2546 names) or the agent's Qdrant catalog is invalidated:

```bash
cd mcp_gateway
uv run pytest gateway/tests/                    # offline name-freeze test
uv run python scripts/dump_tools.py --url http://localhost:8001/sse/ --out live.txt
diff baseline_tools.txt live.txt                # must be empty
```

If a diff appears **unintentionally**: stop, find what changed (fastmcp version? edited spec? manifest?) and revert. If intentional: [Gateway Upgrades](gateway_upgrades.md).

## Add a device to the inventory

### Option A — frontend / admin API (recommended)

Set `GATEWAY_ADMIN_TOKEN` (gateway) and `MCP_GATEWAY_ADMIN_URL` + `MCP_GATEWAY_ADMIN_TOKEN` (app) — compose wires all three from `GATEWAY_ADMIN_TOKEN` in `.env`. Then, in the dashboard: Inventory → Add Component → enable **MCP managed device** and fill host/port/token. The app calls the gateway admin API, which encrypts the token, writes `devices/managed.yaml` and hot-reloads the registry — **no restart needed**. The row shows an `MCP synced` / `MCP sync error` badge; on error, edit the component, re-enter the token and save to retry.

Direct API usage (same thing the app does):

```bash
curl -X POST http://localhost:8001/admin/tenants/fake_client/devices \
  -H "X-Admin-Token: $GATEWAY_ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"id":"fw_branch_2","name":"Branch 2 FortiGate","type":"fortios",
       "connection":{"host":"10.0.2.1","port":443,"token":"<plaintext>","verify_ssl":false}}'
```

`PATCH`/`DELETE /admin/tenants/<cid>/devices/<id>` update/remove; `GET .../devices` lists (tokens redacted); `POST /admin/reload` forces a re-read after out-of-band edits.

Tenant inventories are provisioned automatically: creating a tenant in the app (`POST /tenants` or `register-tenant`) calls `POST /admin/tenants` on the gateway, which creates `inventory/tenants/<cid>/` + `tenant.yaml`. Deleting the tenant in the app calls `DELETE /admin/tenants/<cid>`; the gateway refuses (409) while hand-maintained device YAML files exist under `devices/` — remove those on the gateway host first.

### Option B — hand-edit a YAML file

1. Encrypt the device API token: see [Gateway Secrets](gateway_secrets.md).
2. Edit `mcp_gateway/inventory/tenants/<customer_id>/devices/<file>.yaml` (gitignored; sample: `firewalls.example.yaml`; **do not edit `managed.yaml`** — it is owned by the admin API):
   ```yaml
   - id: "fw_branch_2"            # must match the id used in the agent's context.yaml
     name: "Branch 2 FortiGate"
     type: "fortios"              # must match the pack's device_type
     primary: false               # exactly one device should be primary
     connection:
       host: "10.0.2.1"
       port: 443
       token: "ENC(...)"
       verify_ssl: false
   ```
3. Restart the gateway, or `POST /admin/reload` if the admin API is enabled.

**Verification**: call the `fgt_get_inventory_tree` tool (or check startup log `Loaded N 'fortios' devices`), then a read-only call with `device: fw_branch_2`.

## Gotchas

- The `device` header routes per request; without it, calls go to the `primary: true` device.
- Devices with wrong `type` are silently filtered out for the pack — check the startup device count.
- The gateway serves the tenant in `ACTIVE_CUSTOMER_ID` only; the admin API writes any tenant's files but only hot-reloads the active tenant.
- Hand-maintained devices cannot be modified through the admin API (409) — edit the file. A `primary: true` in a hand-maintained file outranks any managed primary (file order); the API warns when this happens.
- In compose the inventory volume must stay **read-write** (`./mcp_gateway/inventory:/app/inventory`) or every admin write fails.
- Sync drift (app says managed, gateway lost the entry): re-save the component from the UI (re-enter the token) — the app falls back between POST/PATCH automatically.
