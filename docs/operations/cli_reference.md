# CLI Reference

> Every command-line entry point of the platform: `src/main.py` commands, utility modules, and analysis scripts.

**Common prerequisites**: `.env` populated, PostgreSQL reachable and migrated (`uv run alembic upgrade head`), Qdrant reachable. DB-touching commands also need `OPENAI_API_KEY` (embeddings). Every `src/main.py` invocation first loads capability packs and discovers MCP tools, so the MCP Gateway should be running (a warning is logged if not).

## Application CLI — `uv run python src/main.py <command>`

| Command | Usage | Effect |
|---|---|---|
| `init-db` | `init-db` | Ensures all 6 Qdrant collections + payload indexes exist. Does **not** run Postgres migrations (use Alembic) |
| `register-tenant` | `register-tenant --file data/tenants/<id>/tenant.yaml` | Seeds `PlatformTenant` + `CapabilityScope` rows from YAML |
| `seed-context` | `seed-context --file data/tenants/<id>/context.yaml` | Creates/updates the tenant's `ClientContext` (inventory, dependencies, baselines, known changes) |
| `seed-kb` | `seed-kb --dir <docs_dir> --customer-id <id>` | Embeds a directory of knowledge-base documents into Qdrant `knowledge_base` for that tenant |
| `create-admin-key` | `create-admin-key [name]` | Bootstraps the `__platform__` tenant and prints a platform-admin API key **once** |
| `create-tenant-key` | `create-tenant-key <customer_id> [name]` | Creates an API key for an existing tenant. **Role is always `operator`** (`tickets:write`); there is no role argument |
| `create-admin` | `create-admin [email]` | Creates a Super Admin **JWT user** with a random one-time password (`must_change_password`) |
| `test` | `test` | Runs a hardcoded test ticket. **Warning: executes the legacy 13-agent graph**, not the Engineer — use the API to exercise the current agent |

## Utility modules — `uv run python -m src.utils.<module>`

| Module | Effect |
|---|---|
| `init_qdrant` | Create/ensure all Qdrant collections + indexes (idempotent; also run by the Docker entrypoint) |
| `clean_qdrant` | ⚠️ **DESTRUCTIVE** — deletes **all 6** Qdrant collections (knowledge_base, evidence, tool_knowledge, resolved_tickets, adaptive_fixes, tool_catalog). They are recreated empty on next init; re-populating `tool_catalog` costs LLM classification calls (see [Tool Catalog](tool_catalog.md)) |
| `clean_and_reseed --dir <kb> --customer-id <id>` | Nuke → recreate collections (hybrid mode if `QDRANT_HYBRID_ENABLED=true`) → re-seed the KB |

## Analysis scripts — `uv run python scripts/<script>`

| Script | Effect |
|---|---|
| `dump_tool_catalog.py --customer-id <id> [--output dump.json]` | Dumps indexed `tool_catalog` payloads from Qdrant (no OpenAI key needed) |
| `evaluate_tool_catalog.py` | Retrieval-quality evaluation harness for the tool catalog |

## Other executables

| Invocation | Effect |
|---|---|
| `uv run python run_mock.py --file <ticket.txt> [--fast]` | Runs a file-based ticket through the **legacy graph**; `--fast` sets `TEST_MODE_FAST` |
| `uv run streamlit run streamlit_app.py` | Legacy local Streamlit UI (the React frontend is the current dashboard) |
| `cd frontend && npm run dev` | React dashboard in dev mode (Vite, proxies `/api` to `:8000`) |

## Gateway CLI

The MCP Gateway is a separate uv project — see [Gateway Operations](gateway_operations.md) and [Gateway Secrets](gateway_secrets.md).
