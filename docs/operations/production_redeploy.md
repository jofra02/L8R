# Production Redeploy

> How to ship a new version onto an existing production stack without losing data: backup, build, gate, deploy, verify, rollback.

Scope: routine code/config updates on a server that already runs the compose stack. First-time installation is covered in [Deployment](../setup/deployment.md). Assumed environment: Linux server, Docker Engine + compose plugin, repo cloned, code delivered via `git pull`/checkout, images built locally.

## State model — what survives what

| State | Location | `docker compose up -d` / rebuild | `docker compose down` | `docker compose down -v` |
|---|---|---|---|---|
| PostgreSQL data | named volume `pgdata` | survives | survives | **DESTROYED** |
| Qdrant vectors (KB, tool catalog, evidence) | named volume `qdrant_data` | survives | survives | **DESTROYED** |
| Evidence blobs | named volume `evidence_data` | survives | survives | **DESTROYED** |
| Gateway device inventory (encrypted tokens) | host bind `./mcp_gateway/inventory/` | survives | survives | survives |
| Secrets/config (`.env`, `INVENTORY_MASTER_KEY`) | host files | survives | survives | survives |
| Application code / images | git working tree / local images | rebuilt each deploy | — | — |

**Never run `docker compose down -v` in production.** A redeploy never needs it: containers are recreated in place and the volumes stay attached. Redeploying is not destructive by design — the risk window is database migrations, which is what the automatic backup covers.

## Standard redeploy

From the repo root on the server:

```bash
bash scripts/deploy/redeploy.sh --ref v1.2.3   # deploy a tag/branch/SHA
bash scripts/deploy/redeploy.sh                # git pull --ff-only on the current branch
```

| Flag | Effect |
|---|---|
| `--ref <tag\|branch\|sha>` | Checkout this ref instead of pulling |
| `--no-pull` | Deploy the working tree as-is (config-only deploys, see below) |
| `--skip-backup` | Skip the pre-deploy backup. Discouraged; requires typing `YES` (skipped by `--yes`) |
| `--services "app frontend"` | Partial redeploy of specific compose services |
| `--no-cache` | Rebuild all image layers from scratch (escape hatch for a corrupted/suspect layer cache) |
| `--allow-name-drift` | Accept an intentional gateway tool-name baseline change |
| `--rollback [backup-dir]` | Revert code to the SHA recorded in a backup manifest |
| `--yes` | Non-interactive (skips confirmation prompts) |

## What the script does

1. **Preflight** — required binaries, stack running, clean working tree (unless `--no-pull`), `.env` sanity: fails on placeholder `DB_PASS`/`JWT_SECRET_KEY`/missing `OPENAI_API_KEY`; warns on empty `GATEWAY_ADMIN_TOKEN`/`INVENTORY_MASTER_KEY` and `APP_ENV != production`.
2. **Backup** — runs `scripts/deploy/backup.sh`: PostgreSQL `pg_dump -Fc`, per-collection Qdrant snapshots (downloaded out of the volume), secrets tar (inventory + `.env`), evidence blobs. Stored under `backups/<UTC-stamp>_<sha>_predeploy/` with a manifest recording the pre-deploy ref. See [Backup & Restore](backup_restore.md).
3. **Fetch** — `git fetch` + checkout of `--ref`, or `git pull --ff-only`.
4. **Build** — `docker compose build --pull` for the target services (`--pull` refreshes base images; add `--no-cache` for a full rebuild). The deployed git SHA is baked into each image as the `org.opencontainers.image.revision` label. Runs **before** the live stack is touched: a build failure aborts with production intact and the previous ref restored.
5. **Name-freeze gate** — boots the freshly built gateway image offline and compares its generated tool names against `mcp_gateway/baseline_tools.txt` (same assertion as `test_name_freeze.py`). A rename would silently invalidate the Qdrant `tool_catalog`; the gate aborts the deploy before that can happen. Intentional changes (new packs, fastmcp upgrade) require regenerating the baseline and deploying with `--allow-name-drift` — see [Gateway Upgrades](gateway_upgrades.md).
6. **Confirm** — summary (old SHA → new SHA, services, backup dir); Enter to proceed.
7. **Deploy** — `docker compose up -d --wait`. Compose recreates only containers whose image or configuration changed; postgres and qdrant run pinned images and are not touched. Recreating the app runs `alembic upgrade head` in its entrypoint ([Database Migrations](database_migrations.md)); the healthcheck `start_period` covers migration time, so `--wait` doubles as the migration gate. On failure the script prints the app logs and the rollback command — it does not roll back automatically.
8. **Verify images** — for each rebuilt service, asserts the running container's `org.opencontainers.image.revision` label equals the deployed SHA and its image ID equals the freshly built image. This proves the deploy actually shipped the new code — a stale layer cache or a container `up` failed to recreate fails the deploy loudly instead of passing silently.
9. **Verify health** — `/health` (liveness), poll `/ready` (readiness incl. tool indexing; ceiling 35 min, override with `READY_TIMEOUT_SECONDS=<s>`), gateway `/sse/` probe, frontend probe. A `degraded` readiness is reported as a warning, not a failure.

Expected downtime: the app is unavailable for roughly 10–60 seconds while its container is recreated and migrations run. Postgres, Qdrant and the gateway keep serving throughout (the gateway only restarts when its own image changed).

## Manual verification checklist

- [ ] `docker compose ps` — all services healthy.
- [ ] `GET /health` returns 200 immediately.
- [ ] `GET /ready` — `ready` is nominal. `initializing` means tool indexing is running (normal for up to ~30 min after catalog changes; the platform serves traffic meanwhile). `degraded` means indexing failed — recoverable without redeploy, see [Tool Catalog](tool_catalog.md).
- [ ] Frontend login works; dashboard loads.
- [ ] Submit a smoke ticket and confirm a run starts.

## Rollback

**Code-only rollback** (bad release, app misbehaving, migrations harmless):

```bash
bash scripts/deploy/redeploy.sh --rollback                  # newest backup's manifest
bash scripts/deploy/redeploy.sh --rollback backups/<dir>    # a specific one
```

Checks out the pre-deploy ref from the backup manifest, rebuilds (near-instant thanks to the layer cache) and redeploys. The database is **not** restored: migrations applied by the failed deploy remain in place, which is safe because upgrade migrations are additive by policy. **Never run `alembic downgrade` in production** — the downgrade paths drop tables/columns and destroy data ([Database Migrations](database_migrations.md)).

**Gateway rollback** — same command. If the failed deploy had changed tool names (deployed with `--allow-name-drift`), the Qdrant `tool_catalog` may reference the new names; re-index per [Tool Catalog](tool_catalog.md).

**Rollback with database restore** — only when the new code corrupted or deleted data, not merely because migrations ran. Restore the pre-deploy dump from the backup directory following [Backup & Restore](backup_restore.md), accepting the loss of all writes made after that dump. Roll the code back first, then restore.

## .env changes

Modern compose includes `env_file` content in the service configuration hash, so after editing `.env` a plain `docker compose up -d` recreates the app with the new values. The sanctioned procedure for config-only deploys is:

```bash
bash scripts/deploy/redeploy.sh --no-pull
```

which still takes a backup and verifies health. Two traps:

- **`DB_PASS`** — changing it in `.env` does not change the actual password stored inside the initialized `pgdata` volume; postgres only reads `POSTGRES_PASSWORD` on first initialization. Rotate with `ALTER USER <user> WITH PASSWORD '...'` inside postgres first, then update `.env`.
- **`INVENTORY_MASTER_KEY`** — rotating it without re-encrypting the gateway inventory makes every stored device token undecryptable. Follow the rotation procedure in [Gateway Secrets](gateway_secrets.md). Losing this key is unrecoverable; it is included in the backup secrets tar for exactly this reason.

## Special cases

- **Frontend-only change**: `bash scripts/deploy/redeploy.sh --services frontend`. No migrations, no gateway involvement; the backup still runs by default (cheap insurance).
- **New gateway appliance pack / spec changes**: follow [Gateway Upgrades](gateway_upgrades.md) — regenerate `baseline_tools.txt`, deploy with `--allow-name-drift`. Genuinely new tools and tools with **changed descriptions** are indexed incrementally on the next startup (minutes; only those go through LLM classification, bounded by `TOOL_CATALOG_REINDEX_CAP` per boot); renamed tools require a full `tool_catalog` re-index (~30 min, LLM cost).
- **Full catalog re-index**: `/ready` reports `initializing` for the duration; `search_tool_catalog` may return partial results meanwhile. The API and frontend keep serving.

## Backups and retention

Layout: `backups/<UTC-stamp>_<git-sha>[_label]/` at the repo root (gitignored), containing the postgres dump, downloaded Qdrant snapshots, `inventory_and_env.tgz`, optional `evidence.tgz`, and `manifest.txt`. The standalone script is usable outside deploys:

```bash
bash scripts/deploy/backup.sh [--no-evidence] [--keep N] [--label <str>]
```

Retention: the newest 5 backups are kept by default (`--keep N` to change); older ones are pruned after each successful backup. Off-server copies are the operator's responsibility — at minimum copy `inventory_and_env.tgz` (contains `INVENTORY_MASTER_KEY` and all platform secrets; store it encrypted/restricted) and the postgres dump. Run a restore drill periodically per [Backup & Restore](backup_restore.md).

## Gotchas

- The redeploy script refuses a dirty working tree unless `--no-pull` — production servers should not accumulate local edits.
- `--skip-backup` exists for emergencies only. A failed migration without a pre-deploy dump has no safe database rollback.
- The name-freeze gate runs the check inside the freshly built image (`docker compose run --no-deps`), so it needs no pytest or uv on the server.
- If `/ready` reports `degraded`, do not redeploy to "fix" it — indexing failures are diagnosed and re-triggered per [Tool Catalog](tool_catalog.md).
- Compose project namespacing: the scripts respect `COMPOSE_PROJECT_NAME`, which allows rehearsing a deploy against a disposable parallel stack on alternate ports.
