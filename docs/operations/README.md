# Operations Manual

> One runbook per recurring procedure. Each follows the same skeleton: Purpose / When to run / Prerequisites / Steps / Verification / Rollback / Gotchas.

## Daily operations

| Runbook | When you need it |
|---|---|
| [Ticket Operations](ticket_operations.md) | Submit a ticket, check a run, read the report, triage a failed run |
| [CLI Reference](cli_reference.md) | Any `src/main.py` / utils command — args and effects |
| [API Keys & Users](api_keys_and_users.md) | Bootstrap an admin, create/rotate/revoke API keys, manage JWT users |
| [Tenant Onboarding](tenant_onboarding.md) | Bring a new customer onto the platform end to end |

## Maintenance / rare

| Runbook | When you need it |
|---|---|
| [Production Redeploy](production_redeploy.md) | Ship a new version safely: backup, build, gate, deploy, rollback |
| [Tool Catalog](tool_catalog.md) | Understand indexing; force a re-index (costs LLM calls) |
| [Database Migrations](database_migrations.md) | Run/inspect Alembic migrations |
| [Docker Compose](docker_compose.md) | Stack operations, observability profile, scaling, ports |
| [Gateway Operations](gateway_operations.md) | Run the MCP Gateway, verify name-freeze, add a device |
| [Gateway Secrets](gateway_secrets.md) | Encrypt device tokens, **rotate the master key** |
| [Gateway Upgrades](gateway_upgrades.md) | Add an appliance pack, upgrade fastmcp safely |
| [Backup & Restore](backup_restore.md) | PostgreSQL + Qdrant + evidence store backup/DR |

Component background for all of these: [Components Guide](../architecture/components.md).
