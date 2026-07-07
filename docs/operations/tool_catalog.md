# Tool Catalog

> How MCP tool indexing works and how to force a re-index.

## How indexing works

At API startup, `CapabilityRegistry` ([src/core/registry.py](../../src/core/registry.py)):

1. Discovers tools from every server in `data/mcp/servers.yaml` (the MCP Gateway exposes **2546**).
2. Safety-filters them (`_is_safe`, keyword blocklist) → **2182** registered.
3. **Diff-based indexing** into Qdrant `tool_catalog` (global collection, `customer_id="__global__"`): only tools not already indexed are embedded and classified. When nothing changed the log shows:
   `tool_catalog up to date (2182 tools). Skipping indexing.`
4. New tools go through an **LLM classification pass** (IT-domain categories, discovery tier, identifiers) in batches of 15 — this is the expensive part.
5. Stale entries (indexed but no longer registered) are logged, **not** deleted.

There is **no force-reindex flag**.

## When to force a re-index

- Tool names changed (fastmcp upgrade, appliance pack changes — see [Gateway Upgrades](gateway_upgrades.md)).
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

> **Cost warning**: a full re-index embeds and LLM-classifies ~2182 tools (batches of 15) — expect several minutes and real OpenAI spend.

## Verification

- Startup log ends with `tool_catalog up to date (2182 tools)` on the **second** boot after re-indexing.
- `uv run python scripts/dump_tool_catalog.py --customer-id fake_client` → count matches 2182.
- A ticket run's `search_tool_catalog` calls return relevant tools.

## Gotchas

- The catalog is **global** (shared across tenants); per-tenant restriction happens at execution time via capability scopes, not at search time.
- Re-indexing requires the gateway to be up — an empty registry re-indexes nothing.
- The 2546→2182 delta is the safety filter, not an error.
