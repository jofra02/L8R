# API Keys & Users

> Bootstrap the first admin, manage JWT users, create/rotate/revoke API keys.

**The real access model** (important — some older docs overstated this):

- **API keys** (`sk_live_...`) always carry role `operator` with **`tickets:write` only**. They are for machine ticket ingestion. They cannot manage keys, users, or tenants.
- **JWT users** carry the role hierarchy `viewer < operator < tenant_admin < platform_admin` plus permission profiles; all administrative endpoints require a JWT session.

## Bootstrap the first admin

```bash
uv run python src/main.py create-admin admin@example.com
# Prints a random one-time password (must_change_password=true)
```

Log in and change the password:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "<one-time-password>"}'
# → {access_token, refresh_token}

curl -X POST http://localhost:8000/api/v1/auth/change-password \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"current_password": "<one-time-password>", "new_password": "<strong-password>"}'
```

Password policy: min 12 chars, uppercase + symbol required (`src/config.py`).

## API keys

Via CLI (no server needed):

```bash
uv run python src/main.py create-admin-key "platform-ops"     # platform-admin key (bootstrap only)
uv run python src/main.py create-tenant-key fake_client "ci"  # tenant key (operator, tickets:write)
```

Via API (JWT session required):

```bash
# Create
curl -X POST http://localhost:8000/api/v1/auth/keys \
  -H "Authorization: Bearer <jwt_access_token>" -H "Content-Type: application/json" \
  -d '{"name": "ci-pipeline"}'
# List / revoke / rotate
curl http://localhost:8000/api/v1/auth/keys -H "Authorization: Bearer <jwt>"
curl -X DELETE http://localhost:8000/api/v1/auth/keys/<key_id> -H "Authorization: Bearer <jwt>"
curl -X POST http://localhost:8000/api/v1/auth/keys/<key_id>/rotate -H "Authorization: Bearer <jwt>"
```

Raw keys are shown **once** at creation/rotation. Rotation revokes the old key and mints a replacement with the same metadata.

## Users & permissions (JWT)

Managed via the API routers (see [API summary tables](../integrations/api_reference.md#router-summaries)):
- `/api/v1/users` — create/update users, reset passwords (`users:manage`).
- `/api/v1/profiles` — permission profiles; `GET /profiles/permissions` lists all grantable permissions.
- `/api/v1/tenants/{customer_id}/users` — assign users to tenants.
- `POST /api/v1/auth/switch-tenant` — switch the active tenant of a session.

## Verification

`GET /api/v1/auth/me` with either credential returns the resolved context (`customer_id`, `role`).

## Gotchas

- A `role` field sent to `POST /auth/keys` is **ignored** — keys are always operator.
- Losing all admin users is recoverable: `create-admin` can always mint another Super Admin from the CLI.
- `JWT_SECRET_KEY` must be changed from its default in production (`.env`).
