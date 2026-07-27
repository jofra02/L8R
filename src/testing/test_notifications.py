"""NotificationService (n8n webhook) tests (no DB, no network).

Verifies:
1. Payload builders produce the exact envelope for both events.
2. Disabled (N8N_WEBHOOK_URL unset) -> notify_* is a no-op: no row, no POST.
3. HTTP 200 -> delivered with response body stored; non-2xx -> failed;
   connection error -> failed WITHOUT raising (best-effort guarantee).
4. Row is persisted BEFORE the POST attempt (resend survives a dead POST).
5. Resend: increments attempts, re-sends the identical stored payload,
   flips failed -> delivered; tenant mismatch -> None; unconfigured -> RuntimeError.
6. A persistence failure inside notify_* never raises into the caller.

Run: uv run pytest src/testing/test_notifications.py
"""

import pytest

from src.config import settings
from src.core.models import Ticket
from src.core.orm import NotificationDeliveryORM
from src.notifications.payloads import (
    build_ticket_ingested_payload,
    build_run_completed_payload,
)
from src.notifications.service import NotificationService

TICKET = Ticket(
    id="tk_1",
    external_id="INC0012345",
    mode="incident",
    text="VPN tunnel down between HQ and branch " + "x" * 300,
    severity="high",
    source="webhook:portal",
)

STATE = {
    "final_answer": "## Report\nRoot cause: phase2 selector mismatch.",
    "hypotheses": [
        {"summary": "Selector mismatch", "confidence": 0.9, "status": "validated",
         "evidence_refs": ["ev_1"], "rationale": "Config diff"},
    ],
    "structured_facts": [
        {"key": "tunnel_status", "value": "down", "source_evidence_id": "ev_1", "confidence": 1.0},
    ],
    "plan": {"diagnosis_steps": ["step"], "proposed_changes": [], "validation": [], "rollback": []},
    "case_status": "resolved",
    "evidence_refs": ["ev_1"],
}


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class StubService(NotificationService):
    """No-DB service: records persistence and POSTs in memory."""

    def __init__(self, response=None, post_error=None):
        self.response = response
        self.post_error = post_error
        self.persisted = {}
        self.posts = []
        self.dispatched = []

    async def _tenant_name(self, customer_id):
        return "ACME Corp"

    async def _persist_delivery(self, delivery_id, event_type, customer_id, ticket_id, run_id, payload):
        self.persisted[delivery_id] = NotificationDeliveryORM(
            id=delivery_id, customer_id=customer_id, event_type=event_type,
            ticket_id=ticket_id, run_id=run_id, payload=payload,
            status="pending", attempts=0,
        )

    async def _get_delivery(self, delivery_id, customer_id=None):
        row = self.persisted.get(delivery_id)
        if row is not None and customer_id is not None and row.customer_id != customer_id:
            return None
        return row

    async def _dispatch(self, delivery_id):
        self.dispatched.append(delivery_id)
        row = self.persisted[delivery_id]
        await self._apply_attempt(row)

    async def _post(self, payload):
        self.posts.append(payload)
        if self.post_error:
            raise self.post_error
        return self.response


# --- Payload builders ---

def test_ticket_ingested_payload_shape():
    p = build_ticket_ingested_payload("ev-id", "t1", "ACME Corp", TICKET, "run_1")
    assert p["event"] == "ticket.ingested"
    assert p["event_id"] == "ev-id"
    assert p["tenant"] == {"customer_id": "t1", "name": "ACME Corp"}
    assert p["run"] == {"id": "run_1", "status": "queued"}
    t = p["ticket"]
    assert t["id"] == "tk_1" and t["source"] == "webhook:portal"
    assert t["external_id"] == "INC0012345"
    assert t["mode"] == "incident" and t["severity"] == "high"
    assert len(t["title"]) == 200, "title must truncate to 200 chars"
    assert "timestamp" in p


def test_ticket_ingested_payload_blank_external_id():
    ticket = TICKET.model_copy(update={"external_id": None})
    p = build_ticket_ingested_payload("ev-id", "t1", "ACME Corp", ticket, "run_1")
    assert p["ticket"]["external_id"] == "", "unset external_id must be sent as blank string"


def test_run_completed_payload_shape():
    p = build_run_completed_payload("ev-id", "t1", "ACME Corp", TICKET, "run_1", STATE)
    assert p["event"] == "run.completed"
    assert p["run"] == {"id": "run_1", "status": "completed", "hypothesis_count": 1}
    assert p["final_answer"] == STATE["final_answer"]
    f = p["findings"]
    assert f["summary"] == STATE["final_answer"]
    assert f["hypotheses"] == STATE["hypotheses"]
    assert f["facts"] == STATE["structured_facts"]
    assert f["plan"] == STATE["plan"]
    assert f["case_status"] == "resolved"
    assert f["evidence_refs"] == ["ev_1"]


def test_run_completed_payload_empty_state():
    p = build_run_completed_payload("ev-id", "t1", None, TICKET, "run_1", {})
    assert p["run"]["hypothesis_count"] == 0
    assert p["final_answer"] == ""
    assert p["findings"]["facts"] == [] and p["findings"]["plan"] == {}


# --- Disabled mode ---

async def test_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", None)
    svc = StubService()
    await svc.notify_ticket_ingested(TICKET, "run_1", "t1")
    await svc.notify_run_completed(TICKET, "run_1", "t1", STATE)
    assert svc.persisted == {} and svc.posts == []


# --- Dispatch outcomes ---

def make_row(payload=None):
    return NotificationDeliveryORM(
        id="d1", customer_id="t1", event_type="ticket.ingested",
        ticket_id="tk_1", run_id="run_1",
        payload=payload or {"event": "ticket.ingested"},
        status="pending", attempts=0,
    )


async def test_attempt_2xx_delivered(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")
    svc = StubService(response=FakeResponse(200, '{"message":"Workflow was started"}'))
    row = make_row()
    await svc._apply_attempt(row)
    assert row.status == "delivered"
    assert row.attempts == 1 and row.last_attempt_at is not None
    assert row.response_status == 200
    assert row.response_body == '{"message":"Workflow was started"}'
    assert row.error is None


async def test_attempt_500_failed(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")
    svc = StubService(response=FakeResponse(500, "boom"))
    row = make_row()
    await svc._apply_attempt(row)
    assert row.status == "failed"
    assert row.response_status == 500 and row.error == "HTTP 500"


async def test_attempt_connection_error_failed_no_raise(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")
    svc = StubService(post_error=ConnectionError("refused"))
    row = make_row()
    await svc._apply_attempt(row)  # must not raise
    assert row.status == "failed" and "refused" in row.error
    assert row.attempts == 1


async def test_response_body_truncated(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")
    svc = StubService(response=FakeResponse(200, "x" * 10000))
    row = make_row()
    await svc._apply_attempt(row)
    assert len(row.response_body) == 4000


# --- Notify flow: persist before POST ---

async def test_run_completed_persists_before_post(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")

    class OrderChecking(StubService):
        def __init__(self):
            super().__init__(response=FakeResponse(200))
            self.persisted_at_post = None

        async def _post(self, payload):
            self.persisted_at_post = len(self.persisted)
            return await super()._post(payload)

    svc = OrderChecking()
    await svc.notify_run_completed(TICKET, "run_1", "t1", STATE)
    assert svc.persisted_at_post == 1, "row must be persisted before the POST"
    delivery = next(iter(svc.persisted.values()))
    assert delivery.status == "delivered"
    assert delivery.payload["event"] == "run.completed"
    assert delivery.payload["event_id"] == delivery.id


async def test_persist_failure_never_raises(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")

    class Broken(StubService):
        async def _persist_delivery(self, *a, **kw):
            raise RuntimeError("db down")

    svc = Broken(response=FakeResponse(200))
    await svc.notify_ticket_ingested(TICKET, "run_1", "t1")  # must not raise
    await svc.notify_run_completed(TICKET, "run_1", "t1", STATE)  # must not raise
    assert svc.posts == []


# --- Resend ---

async def test_resend_identical_payload_flips_to_delivered(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")
    svc = StubService(post_error=ConnectionError("refused"))
    await svc.notify_run_completed(TICKET, "run_1", "t1", STATE)
    delivery = next(iter(svc.persisted.values()))
    assert delivery.status == "failed" and delivery.attempts == 1
    first_payload = svc.posts[0]

    svc.post_error = None
    svc.response = FakeResponse(200, "ok")
    row = await svc.resend(delivery.id, "t1")
    assert row.status == "delivered" and row.attempts == 2
    assert svc.posts[1] == first_payload, "resend must re-send the stored payload unchanged"


async def test_resend_tenant_mismatch_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", "http://n8n.local/webhook")
    svc = StubService(response=FakeResponse(200))
    await svc.notify_run_completed(TICKET, "run_1", "t1", STATE)
    delivery_id = next(iter(svc.persisted))
    assert await svc.resend(delivery_id, "other_tenant") is None


async def test_resend_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_URL", None)
    svc = StubService()
    with pytest.raises(RuntimeError):
        await svc.resend("whatever", "t1")
