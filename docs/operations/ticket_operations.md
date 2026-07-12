# Ticket Operations

> Submit a ticket, follow the run, read the report, triage failures.

**Prerequisites**: API running, tenant onboarded, API key in hand. All calls: `Authorization: Bearer <key>`, base `http://localhost:8000`.

## Submit

```bash
curl -X POST http://localhost:8000/api/v1/tickets \
  -H "Authorization: Bearer <key>" -H "Content-Type: application/json" \
  -d '{
    "text": "VPN tunnel between site A and site B is down since 09:30",
    "severity": "high",
    "mode": "incident",
    "source": "manual",
    "external_id": "INC0012345"
  }'
# → 202 {"ticket_id": "...", "job_id": "..."}
```

`mode`: `incident` | `change` | `validation` | `inquiry` (defaults to `incident`). Legacy no-key variant: `POST /api/v1/webhook/{source}` with header `X-Customer-ID: <customer_id>`. Full endpoint contract: [API Reference](../integrations/api_reference.md#tickets--apiv1tickets).

Execution is a fire-and-forget background task in the API process — **runs in flight are lost if the API restarts** (no durable queue); re-submit or use `retry`.

## Follow the run

```bash
curl "http://localhost:8000/api/v1/runs?ticket_id=<ticket_id>" -H "Authorization: Bearer <key>"   # status
curl "http://localhost:8000/api/v1/runs/<run_id>/timeline"    -H "Authorization: Bearer <key>"   # node events
curl "http://localhost:8000/api/v1/runs/<run_id>/tool-calls"  -H "Authorization: Bearer <key>"   # MCP audit trail
```

## Retrieve results

```bash
curl http://localhost:8000/api/v1/tickets/<id>/report      -H "Authorization: Bearer <key>"
curl http://localhost:8000/api/v1/tickets/<id>/hypotheses  -H "Authorization: Bearer <key>"
curl http://localhost:8000/api/v1/tickets/<id>/facts       -H "Authorization: Bearer <key>"
curl http://localhost:8000/api/v1/tickets/<id>/plan        -H "Authorization: Bearer <key>"
curl http://localhost:8000/api/v1/tickets/<id>/evidence    -H "Authorization: Bearer <key>"
```

### Interpreting the report

- **`case_status`**: `resolved` (root cause identified with evidence) / `needs_human` (agent needs information or a decision) / `blocked` (couldn't investigate — check tool errors).
- **`hypotheses`**: ranked, each with `confidence` (0–1), `status` (verified/proposed/rejected) and `evidence_refs` pointing at snapshots — a "verified" hypothesis is backed by actual tool output.
- **`plan`**: `diagnosis_steps` → `proposed_changes` → `validation` → `rollback`. Proposed changes are **never executed** by the platform; they are for a human to apply.
- **`facts`**: discovered key/values with evidence provenance.

## Triage a failed run

1. `GET /runs/<run_id>` — `status=failed` + error field.
2. `GET /runs/<run_id>/tool-calls` — look for repeated `error` statuses (device unreachable? tool blocked by safety?).
3. API logs (`logs/agent.log*` or `docker compose logs app`).
4. Langfuse trace (if enabled): find the trace by `run_id`, inspect the LLM turns — timeouts show as truncated loops (`ENGINEER_TIMEOUT_SECONDS`, default 600s; iteration cap `ENGINEER_MAX_ITERATIONS`).
5. Retry: `POST /api/v1/tickets/<id>/retry` (new run, same ticket).

## Gotchas

- `main.py test` / `run_mock.py` exercise the **legacy graph** — don't use them to debug Engineer behavior.
- If every `execute_tool` fails with connection errors, check the MCP Gateway health first (`docker compose ps mcp-gateway`, [Gateway Operations](gateway_operations.md)).
- Evidence dedup: identical tool+args within a run are skipped by design (the agent is told the duplicate exists).
