# Outbound Notifications

Global outbound webhook egress to an n8n endpoint. Disabled unless `N8N_WEBHOOK_URL` is set — with the variable unset, no deliveries are attempted and no rows are written.

Source: `src/notifications/` (`service.py` dispatch + persistence, `payloads.py` payload contracts).

## Events

| Event | Fired from | Content |
|---|---|---|
| `ticket.ingested` | `IngestionService`, inside the HTTP request path | Ticket metadata (id, external_id, source, mode, severity, truncated title, timestamps) + run id with status `queued` |
| `run.completed` | Background run execution, after the run finishes | Same ticket block + full findings: `final_answer`, hypotheses, structured facts, plan, case status, evidence refs |

Both events are **best-effort by contract**: no notification failure can raise into the ingestion or run path (same guarantee as `AuditService` and `GatewayAdminClient`).

## Payload envelope

Built by pure functions in `src/notifications/payloads.py` (no I/O). Every payload carries `event`, `event_id` (= delivery id), `timestamp`, a `tenant` block (`customer_id`, resolved tenant name), a `ticket` block, and a `run` block. `run.completed` adds `final_answer` and a `findings` object sourced from the sanitized final `GlobalState` already persisted to `agent_runs.state_json`. Any change to these shapes is a contract change for downstream n8n workflows.

## Delivery persistence and resend

Each delivery is persisted to the `notification_deliveries` table (migration `f7a8b9c0d1e2`) **before** the POST, storing the exact payload snapshot plus outcome bookkeeping (`status` pending/delivered/failed, `attempts`, `last_attempt_at`, `response_status`, `response_body` truncated to 4000 chars, `error`). A failed or interrupted send can therefore be resent later with the identical payload.

- `ticket.ingested`: row insert is awaited, the POST is detached (`asyncio.create_task`) to keep request latency flat.
- `run.completed`: already runs in a background task, so the POST is awaited inline.

## API

| Endpoint | Permission | Purpose |
|---|---|---|
| `GET /notifications` | `notifications:read` | Paginated, tenant-scoped delivery list; optional filters `status`, `event_type`, `ticket_id`, `run_id` |
| `POST /notifications/{delivery_id}/resend` | `notifications:manage` | Re-POST the stored payload of a delivery (tenant-scoped); `409 not_configured` when `N8N_WEBHOOK_URL` is unset, `404 not_found` when the delivery does not exist for the tenant |

The frontend exposes a Notifications page under the tenant shell for browsing deliveries and triggering resends.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `N8N_WEBHOOK_URL` | unset | Webhook endpoint. Unset = feature disabled entirely |
| `NOTIFICATION_TIMEOUT` | `10.0` | POST timeout in seconds |
| `NOTIFICATION_AUTH_HEADER_NAME` | unset | Optional static auth header name (e.g. `X-Webhook-Token`) |
| `NOTIFICATION_AUTH_HEADER_VALUE` | unset | Value for the auth header; sent only when both name and value are set |
