# Database Migrations

> Run and inspect Alembic migrations for the PostgreSQL schema.

**When they run automatically**: the Docker entrypoint (`scripts/entrypoint.sh`) runs `alembic upgrade head` + `init_qdrant` on every `app` container start. Host-run development applies them manually.

## Commands

```bash
# Host
uv run alembic upgrade head          # apply pending migrations
uv run alembic current               # show current revision
uv run alembic history --verbose     # list all revisions

# Inside compose
docker compose exec app python -m alembic upgrade head
docker compose exec app python -m alembic current
```

Config: `alembic.ini` (`script_location = src/alembic`); revisions live in `src/alembic/versions/`.

## Creating a migration (development)

```bash
uv run alembic revision --autogenerate -m "describe the change"
# review the generated file — autogenerate misses server defaults and JSON changes
uv run alembic upgrade head
```

## Verification

`uv run alembic current` shows the head revision; the API starts without `relation does not exist` errors.

## Rollback

```bash
uv run alembic downgrade -1          # one step back — verify the down() body exists first
```

Take a [backup](backup_restore.md) before downgrading in anything but local dev.

## Gotchas

- `src/main.py init-db` does **not** run Postgres migrations (Qdrant only) — the reminder it prints is easy to miss.
- Migrations run against `DB_HOST`/`DB_PORT` from `.env` — with a remote DB (e.g. Tailscale) confirm you're pointing at the environment you think you are.
