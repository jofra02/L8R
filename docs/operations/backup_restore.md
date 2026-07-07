# Backup & Restore

> PostgreSQL + Qdrant + evidence store: what to back up, in what order, and how to restore.

## What holds state

| Store | Contents | Loss impact |
|---|---|---|
| PostgreSQL | Tenants, users/RBAC, tickets, runs, audit, contexts, evidence metadata | Total platform state |
| Qdrant (6 collections) | KB, evidence vectors, tool catalog, resolved cases, legacy collections | KB/cases are irreplaceable; `tool_catalog` and `evidence` vectors are **rebuildable** |
| `data/evidence/` | Raw evidence blobs (content-addressable JSON) | Report evidence links break |
| `mcp_gateway/inventory/` + `.env` files | Device credentials (encrypted) + master key | Gateway cannot reach devices |

## Backup procedure

Quiesce first if possible (stop ingesting: pause whatever posts tickets; in-flight runs finish in-process).

```bash
STAMP=$(date +%Y%m%d-%H%M)

# 1. PostgreSQL (compose variant)
docker compose exec postgres pg_dump -U ${DB_USER:-postgres} -Fc support_agent_db > backup_pg_$STAMP.dump

# 2. Qdrant — snapshot per collection (repeat for the ones you care about)
for c in knowledge_base resolved_tickets evidence tool_catalog; do
  curl -X POST "http://localhost:6333/collections/$c/snapshots"
done
# snapshots land in the qdrant_data volume: /qdrant/storage/snapshots/<collection>/

# 3. Evidence blobs
tar czf backup_evidence_$STAMP.tgz data/evidence/

# 4. Secrets/config (encrypted inventory + envs) — store separately/securely
tar czf backup_secrets_$STAMP.tgz mcp_gateway/inventory/ .env mcp_gateway/.env
```

Priority if you must choose: **PostgreSQL + knowledge_base/resolved_tickets snapshots + secrets**. `tool_catalog` can be re-indexed (LLM cost) and evidence vectors re-derived from the blobs.

## Restore procedure

```bash
# 1. PostgreSQL
docker compose exec -T postgres pg_restore -U ${DB_USER:-postgres} --clean --if-exists -d support_agent_db < backup_pg_<stamp>.dump

# 2. Qdrant — upload/restore each snapshot
curl -X PUT "http://localhost:6333/collections/<c>/snapshots/recover" \
  -H "Content-Type: application/json" \
  -d '{"location": "file:///qdrant/storage/snapshots/<c>/<snapshot-name>"}'

# 3. Evidence + secrets
tar xzf backup_evidence_<stamp>.tgz
tar xzf backup_secrets_<stamp>.tgz

# 4. Restart everything
docker compose up -d
```

If `tool_catalog` wasn't restored: just start the API — it re-indexes from the gateway ([Tool Catalog](tool_catalog.md), LLM cost applies).

## Restore drill checklist

- [ ] API starts; `alembic current` shows head.
- [ ] `GET /api/v1/auth/me` works with an existing key.
- [ ] A past ticket's report + evidence render in the frontend.
- [ ] `search_knowledge_base` returns seeded KB content.
- [ ] Gateway decrypts inventory (`Loaded N devices`) — the master key backup matches the inventory backup **from the same date** (see rotation note in [Gateway Secrets](gateway_secrets.md)).

## Gotchas

- Postgres and Qdrant back up independently — restoring them from different moments leaves dangling evidence references (harmless but confusing).
- The `qdrant_data` and `pgdata` docker volumes are NOT covered by repo backups; snapshots/dumps above are the portable form.
