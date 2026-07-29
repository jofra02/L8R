# API Keys & Users

> Bootstrap the first admin, manage JWT users, create/rotate/revoke API keys.

**The real access model** (full contract: [API Reference — Authentication](../integrations/api_reference.md#authentication)):

- **API keys** (`sk_live_...`) carry a **fixed permission set**: `tickets:write`, `tickets:read`, `runs:read`. They are for machine ticket ingestion and result polling. They cannot manage keys, users, tenants, or inventory. A key on the `__platform__` tenant (from `create-admin-key`) has those same three permissions but may act on behalf of any existing tenant by appending `?customer_id=<cid>` to the request.
- **JWT users** get their permissions from the profile assigned per tenant; all administrative endpoints require a JWT session. The old role hierarchy (`viewer < operator < ...`) is deprecated.

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
uv run python src/main.py create-admin-key "platform-ops"     # __platform__ key (cross-tenant via ?customer_id=)
uv run python src/main.py create-tenant-key fake_client "ci"  # tenant key (tickets:write/read + runs:read)
```

Via API (JWT session required):

```bash
# Create (bound to the caller's tenant context)
curl -X POST http://localhost:8000/api/v1/auth/keys \
  -H "Authorization: Bearer <jwt_access_token>" -H "Content-Type: application/json" \
  -d '{"name": "ci-pipeline"}'
# Create a GLOBAL key (platform admin only) — targets a tenant per request
curl -X POST http://localhost:8000/api/v1/auth/keys \
  -H "Authorization: Bearer <jwt_access_token>" -H "Content-Type: application/json" \
  -d '{"name": "n8n-msp", "scope": "global"}'
# Use a global key: the tenant goes in the query string
curl -X POST "http://localhost:8000/api/v1/tickets?customer_id=<tenant>" \
  -H "Authorization: Bearer sk_live_..." -H "Content-Type: application/json" \
  -d '{"text": "VPN down at branch"}'
# List / revoke / rotate
curl http://localhost:8000/api/v1/auth/keys -H "Authorization: Bearer <jwt>"
curl -X DELETE http://localhost:8000/api/v1/auth/keys/<key_id> -H "Authorization: Bearer <jwt>"
curl -X POST http://localhost:8000/api/v1/auth/keys/<key_id>/rotate -H "Authorization: Bearer <jwt>"
```

Raw keys are shown **once** at creation/rotation. Rotation revokes the old key and mints a replacement with the same metadata.

## Users & permissions (JWT)

Managed via the API routers (see the [API Reference](../integrations/api_reference.md#platform-api)):
- `/api/v1/users` — create/update users, reset passwords (`users:manage`).
- `/api/v1/profiles` — permission profiles; `GET /profiles/permissions` lists all grantable permissions.
- `/api/v1/tenants/{customer_id}/users` — assign users to tenants.
- `POST /api/v1/auth/switch-tenant` — switch the active tenant of a session.

## Verification

`GET /api/v1/auth/me` with either credential returns the resolved context (`customer_id`, `role`).

## Gotchas

- A `role` field sent to `POST /auth/keys` is **ignored** — keys are always operator.
- `?customer_id=` is honored only by **global** keys. On a tenant-bound key it is silently ignored and the request acts on the key's own tenant — if you need cross-tenant submission, create a `scope: "global"` key as platform admin.
- Losing all admin users is recoverable: `create-admin` can always mint another Super Admin from the CLI.
- `JWT_SECRET_KEY` must be changed from its default in production (`.env`).
