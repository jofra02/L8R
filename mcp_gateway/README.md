# MCP Gateway

Generic **OpenAPI/Swagger → MCP** gateway: converts vendor API specs into MCP tools and serves them over SSE (`/sse/`) or stdio. This is the tool-execution service of the support_ai_agent platform; the Engineer agent consumes it via `data/mcp/servers.yaml`.

Full documentation: [docs/architecture/mcp_gateway.md](../docs/architecture/mcp_gateway.md) — vendor pack contract, tool name-freeze rules, tenant/inventory model, secrets and key rotation.

## Quick start

```bash
cp .env.example .env          # set INVENTORY_MASTER_KEY and ACTIVE_CUSTOMER_ID
uv sync
uv run python main.py         # SSE on http://localhost:8000/sse/ (8001 with the sample .env)
```

Or as part of the stack: `docker compose up -d mcp-gateway` (from the repo root).

## Tests

```bash
uv run pytest gateway/tests/   # name-freeze: tool names must match baseline_tools.txt
```

## Adding a vendor

Drop a directory under `vendors/<name>/` with a `manifest.yaml` and `specs/<group>/*.json` — no engine changes needed. See the architecture doc for the manifest schema and `vendors/fortinet/` as the reference implementation.
