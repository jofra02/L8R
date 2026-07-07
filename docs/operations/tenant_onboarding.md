# Tenant Onboarding

> Bring a new customer onto the platform end to end.

**Purpose**: register the tenant, load its logical inventory/context, optionally seed its knowledge base, issue an API key, and prove the loop with a test ticket.

**When to run**: once per new customer; re-run individual steps to update context or KB.

**Prerequisites**: stack running (Postgres, Qdrant, MCP Gateway, API), migrations applied. Template files: `data/tenants/fake_client/`.

## Steps

1. **Author the tenant files** under `data/tenants/<customer_id>/`:
   - `tenant.yaml` — id, name, capability scopes (tool allowlist globs like `fgt_*`).
   - `context.yaml` — inventory (devices with ids matching the gateway inventory, e.g. `fgt_casa`), dependencies, baselines, known changes.
2. **Register the tenant**:
   ```bash
   uv run python src/main.py register-tenant --file data/tenants/<customer_id>/tenant.yaml
   ```
3. **Seed the context**:
   ```bash
   uv run python src/main.py seed-context --file data/tenants/<customer_id>/context.yaml
   ```
4. **Seed the knowledge base** (optional — runbooks, vendor docs, known issues as text/markdown files):
   ```bash
   uv run python src/main.py seed-kb --dir <kb_docs_dir> --customer-id <customer_id>
   ```
5. **Issue an API key** (ticket ingestion):
   ```bash
   uv run python src/main.py create-tenant-key <customer_id> "integration"
   ```
   Save the raw key — shown once.
6. **Gateway side** (if this tenant gets its own device inventory): add devices under `mcp_gateway/inventory/tenants/<customer_id>/devices/` and point the gateway at it with `ACTIVE_CUSTOMER_ID=<customer_id>` — see [Gateway Operations](gateway_operations.md). Device `id`s must match the ids used in `context.yaml`.

## Verification

```bash
curl -X POST http://localhost:8000/api/v1/tickets \
  -H "Authorization: Bearer <raw_key>" -H "Content-Type: application/json" \
  -d '{"text": "Health check: list device status", "severity": "low", "mode": "inquiry"}'
# → 202 {ticket_id, job_id}; then follow the run (see Ticket Operations)
```

## Rollback

Tenant removal: `DELETE /api/v1/tenants/{customer_id}` (JWT admin; check `GET .../cascade-warning` first — it cascades tickets, runs, contexts).

## Gotchas

- `register-tenant` and `seed-context` are idempotent-ish (upsert), but `seed-kb` appends — re-seeding the same docs duplicates points; use `clean_and_reseed` for a clean slate.
- Device ids are the contract between agent context and gateway inventory: `context.yaml` ids and `mcp_gateway/inventory/.../devices/*.yaml` ids must match.
- The gateway serves **one tenant per process** (`ACTIVE_CUSTOMER_ID`); multiple tenants with devices need separate gateway instances (or a future multi-tenant gateway).
