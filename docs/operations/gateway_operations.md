# Gateway Operations

> Run the MCP Gateway, verify the tool-name freeze, and manage device inventory.

The gateway is its own uv project at `mcp_gateway/`. Architecture: [mcp_gateway.md](../architecture/mcp_gateway.md).

## Run modes

| Mode | Command | Endpoint |
|---|---|---|
| Compose (normal) | `docker compose up -d mcp-gateway` | `http://localhost:${MCP_GATEWAY_PORT:-8001}/sse/` |
| Host dev | `cd mcp_gateway && uv sync && uv run python main.py` | port from `mcp_gateway/.env` (`SERVER_PORT`) |
| stdio (Claude Desktop etc.) | `SERVER_TRANSPORT=stdio uv run python main.py` | stdio |

All configuration is env-driven (no CLI flags): `ACTIVE_CUSTOMER_ID`, `INVENTORY_MASTER_KEY`, `SERVER_HOST/PORT/TRANSPORT`, `LOG_LEVEL`, `GATEWAY_HTTP_TIMEOUT`.

> The SSE endpoint has **no authentication** (planned future work) — expose it only on trusted networks / the compose network.

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

1. Encrypt the device API token: see [Gateway Secrets](gateway_secrets.md).
2. Edit `mcp_gateway/inventory/tenants/<customer_id>/devices/<file>.yaml` (gitignored; sample: `firewalls.example.yaml`):
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
3. Restart the gateway (inventory is loaded at startup).

**Verification**: call the `fgt_get_inventory_tree` tool (or check startup log `Loaded N 'fortios' devices`), then a read-only call with `device: fw_branch_2`.

## Gotchas

- The `device` header routes per request; without it, calls go to the `primary: true` device.
- Devices with wrong `type` are silently filtered out for the pack — check the startup device count.
- The gateway serves the tenant in `ACTIVE_CUSTOMER_ID` only.
