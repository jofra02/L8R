# MCP Gateway

Generic **OpenAPI/Swagger → MCP** gateway: converts vendor API specs into MCP tools and serves them over SSE (`/sse/`) or stdio. This is the tool-execution service of the support_ai_agent platform; the Engineer agent consumes it via `data/mcp/servers.yaml`.

Full documentation: [docs/architecture/mcp_gateway.md](../docs/architecture/mcp_gateway.md) — vendor pack contract, tool name-freeze rules, tenant/inventory model, secrets and key rotation.

## Quick start

```bash
cp .env.example .env          # set INVENTORY_MASTER_KEY (DEFAULT_TENANT optional — routing is per-request)
uv sync
uv run python main.py         # SSE on http://localhost:8000/sse/ (8001 with the sample .env)
```

Or as part of the stack: `docker compose up -d mcp-gateway` (from the repo root).

## Tests

```bash
uv run pytest gateway/tests/   # name-freeze: tool names must match baseline_tools.txt
```

## Adding an appliance

Packs are organized as `vendors/<vendor>/<appliance>/` — the vendor is the manufacturer, each of its products is a self-contained pack. Drop a directory with a `manifest.yaml` and `specs/<group>/*.json` — no engine changes needed (unless the appliance uses a new auth style: one class + one registry entry in `gateway/auth.py`). See the architecture doc for the manifest schema and the two reference implementations: `vendors/fortinet/fortigate/` (hand-curated FortiOS specs, `bearer_header` auth) and `vendors/fortinet/fortiedr/` (specs generated from the raw Swagger 2.0 exports in `FortiEDR/swagger/v6.2/` by `scripts/convert_fortiedr_specs.py`, `basic_header` auth).

After adding or changing a pack: regenerate the baseline (`uv run python scripts/dump_tools.py --out baseline_tools.txt`), verify pre-existing names are untouched, and re-run the tests.
