# Tool Catalog

> How MCP tool indexing works and how to force a re-index.

## How indexing works

At API startup, `CapabilityRegistry` ([src/core/registry.py](../../src/core/registry.py)):

1. Discovers tools from every server in `data/mcp/servers.yaml` (the MCP Gateway exposes **2776**).
2. Fetches the mounted appliance packs from the gateway admin API (`GET /admin/packs` via `GatewayAdminClient.list_packs()`): vendor, appliance, **version**, prefix, device_type, `pack_key` (`"fortinet/fortigate/7.4"`). Failure is non-fatal — tools then index without pack identity and searches run unscoped.
3. Safety-filters them (`_is_safe`, keyword blocklist) → **2220** registered.
4. **Diff-based indexing** into Qdrant `tool_catalog` (global collection, `customer_id="__global__"`): the diff compares tool **names, descriptions, and args-schema fingerprints** (`schema_hash`, SHA-256 of the canonical schema JSON) against the indexed payload. Missing names are indexed as NEW; tools whose description **or schema** changed (e.g. a gateway pack enriched a summary, an enum, or a parameter description) are re-embedded and re-classified as CHANGED via an in-place upsert on the same deterministic point id — no manual deletion needed. When nothing changed the log shows:
   `tool_catalog up to date (2220 tools, descriptions unchanged). Skipping indexing.`
   The indexed `args_schema` payload is the **raw MCP inputSchema** as the server advertises it (types, formats, enums, per-parameter descriptions) — captured at discovery in `MCPClient.discover_tools()`. It is what `search_tool_catalog` renders to the agent (one line per parameter: type, format, enum values capped at 12, required flag), so the agent can build valid calls on the first attempt instead of guessing argument formats. The pydantic `args_schema` wrapper on external tools is a typeless shell and is never used as a schema source.
5. Each gateway tool resolves to its pack by longest-prefix match (`fgt74_...` → `fortinet/fortigate/7.4`) and its payload carries the **pack partition fields** `pack_vendor`, `pack_product`, `pack_version`, `device_type`, `pack_key` (all keyword-indexed); `vendor` becomes authoritative from the pack. Non-pack tools omit these keys entirely.
6. New and changed tools go through an **LLM classification pass** (IT-domain categories, discovery tier, identifiers) in batches of 15 — this is the expensive part. `TOOL_CATALOG_REINDEX_CAP` (default 200, env-overridable) bounds how many CHANGED tools are re-indexed per startup; any excess is deferred to the next startup (alphabetical order, logged as a WARNING).
7. Stale entries (indexed but no longer registered) are logged, **not** deleted.

There is **no force-reindex flag** (but `_check_catalog_needs_migration` forces a full re-index when it samples a gateway point without `pack_key` **or without `schema_hash`** — legacy catalogs from before the pack partition or before raw-inputSchema capture migrate automatically on startup).

## Version-aware search scoping

The Engineer's `search_tool_catalog` meta-tool scopes results to the tenant's actual appliances: it derives the allowed `pack_key`s from the managed components' `metadata["mcp"]` (`vendor`/`appliance`/`os_version`) via [src/core/pack_matching.py](../../src/core/pack_matching.py) — exact version match, then major.minor prefix ("7.4.5" → pack "7.4"), then deliberate over-inclusion (all versions of the product, logged) when nothing matches. The Qdrant filter admits pack tools with a matching `pack_key` **plus** all tools without pack identity; a tenant with no managed devices searches unscoped (previous behavior). The legacy `ToolSelector` pipeline does **not** apply pack scoping (known gap — it still filters by `vendor` only).

## When to force a re-index

- Tool names changed (fastmcp upgrade, appliance pack changes — see [Gateway Upgrades](gateway_upgrades.md)).
- Parameter documentation changed without the description changing (param docs are part of the embedding, but the diff only compares descriptions).
- Corrupt/outdated classification metadata.
- The startup diff keeps logging large "stale" sets.

## Forced re-index procedure

**Preferred — delete only `tool_catalog`** (keeps KB/evidence/cases intact):

```bash
curl -X DELETE http://localhost:6333/collections/tool_catalog
uv run python -m src.utils.init_qdrant     # recreate empty collection
# restart the API — startup re-indexes everything
```

**Nuclear — wipe all 6 collections** (only if you intend to re-seed everything):

```bash
uv run python -m src.utils.clean_qdrant    # ⚠️ deletes knowledge_base, evidence, etc. too
uv run python -m src.utils.init_qdrant
```

> **Cost warning**: a full re-index embeds and LLM-classifies ~2220 tools (batches of 15) — expect several minutes and real OpenAI spend.

## Verification

- Startup log ends with `tool_catalog up to date (2220 tools)` on the **second** boot after re-indexing.
- `uv run python scripts/dump_tool_catalog.py --customer-id fake_client` → count matches 2220.
- A ticket run's `search_tool_catalog` calls return relevant tools.

## Gotchas

- The catalog is **global** (shared across tenants); per-tenant restriction happens at execution time via capability scopes, not at search time.
- Re-indexing requires the gateway to be up — an empty registry re-indexes nothing.
- The 2776→2220 delta is the safety filter, not an error.
