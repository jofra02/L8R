# Gateway Upgrades

> Add an appliance pack; upgrade fastmcp without silently renaming the 2776 frozen tools.

Both procedures end at the same gate: the **name-freeze check**. Tool names are the contract with the agent's Qdrant `tool_catalog`; any change forces a catalog re-index ([Tool Catalog](tool_catalog.md)).

## A. Add an appliance pack

**Purpose**: expose a new appliance's API as MCP tools. No engine code needed.

1. Create `mcp_gateway/vendors/<vendor>/<appliance>/`:
   - `manifest.yaml` — see the schema in [mcp_gateway.md](../architecture/mcp_gateway.md#appliance-pack-contract); pick a **unique `prefix`** (e.g. `faz`) and a `device_type`.
   - `specs/<group>/*.json` — the OpenAPI/Swagger files, one directory per API group.
   - optional `hooks.py` — `SPEC_FIXES` / `PARAMETER_DOC_APPENDS`.
2. Add devices of the new `device_type` to the inventory ([Gateway Operations](gateway_operations.md)).
3. Build locally and inspect: `uv run python scripts/dump_tools.py --out new.txt` — new tools appear as `<prefix>_...`; existing `fgt74_*` names must be unchanged (`diff <(grep '^fgt74_' new.txt) <(grep '^fgt74_' baseline_tools.txt)` → empty).
4. Regenerate the baseline: `uv run python scripts/dump_tools.py --out baseline_tools.txt` and commit it (this is the intentional-change path of the name-freeze test).
5. Restart the gateway; on the agent side the startup diff-indexing embeds+classifies **only the new tools** (batches of 15, OpenAI cost proportional to pack size).

**Verification**: `uv run pytest gateway/tests/` green with the new baseline; agent startup logs the increased tool count; a `search_tool_catalog` query finds the new tools.

## B. Upgrade fastmcp safely

`fastmcp` is pinned exactly (`mcp_gateway/pyproject.toml`) because `FastMCP.from_openapi` drives tool naming.

1. Bump the pin: `fastmcp==<new>` → `uv lock` → `uv sync`.
2. Run the gate: `uv run pytest gateway/tests/test_name_freeze.py`.
   - **Green** → names survived. Done (commit lock + pin).
   - **Red** → the new version renames tools. Decide:
     - **Abort**: revert the pin (`git checkout pyproject.toml uv.lock && uv sync`).
     - **Proceed**: regenerate `baseline_tools.txt`, commit, then do a **forced re-index** of the agent's tool catalog ([Tool Catalog](tool_catalog.md)) — full LLM classification cost over ~2182 tools.
3. Rebuild the container: `docker compose build mcp-gateway && docker compose up -d mcp-gateway`.

**Verification**: live diff against the (possibly new) baseline is empty; agent startup shows either `up to date` (names kept) or a completed re-index (names changed).

## Gotchas

- Never "fix" the operationId sanitizer's 64-char budget quirk — it renames every hash-truncated tool (documented in `gateway/schema_fixes.py`).
- Editing an existing spec JSON is also a name-risk: re-run the freeze test after any spec change.
- Prefix collisions between packs are not auto-detected — keep prefixes unique by convention.
