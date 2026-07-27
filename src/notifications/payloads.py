"""Pure payload builders for outbound notifications.

No I/O here: builders take already-loaded data and return the exact JSON
envelope persisted in notification_deliveries.payload and POSTed to the
external endpoint. Any change to these shapes is a contract change for
downstream consumers (n8n workflows).
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.core.models import Ticket

TITLE_MAX_CHARS = 200

EVENT_TICKET_INGESTED = "ticket.ingested"
EVENT_RUN_COMPLETED = "run.completed"


def _ticket_block(ticket: Ticket) -> Dict[str, Any]:
    return {
        "id": ticket.id,
        "external_id": ticket.external_id or "",
        "source": ticket.source,
        "mode": ticket.mode,
        "severity": ticket.severity,
        "title": (ticket.text or "")[:TITLE_MAX_CHARS],
        "timestamps": ticket.timestamps or {},
    }


def _tenant_block(customer_id: str, tenant_name: Optional[str]) -> Dict[str, Any]:
    return {"customer_id": customer_id, "name": tenant_name}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_ticket_ingested_payload(
    event_id: str,
    customer_id: str,
    tenant_name: Optional[str],
    ticket: Ticket,
    run_id: str,
) -> Dict[str, Any]:
    return {
        "event": EVENT_TICKET_INGESTED,
        "event_id": event_id,
        "timestamp": _now_iso(),
        "tenant": _tenant_block(customer_id, tenant_name),
        "ticket": _ticket_block(ticket),
        "run": {"id": run_id, "status": "queued"},
    }


def build_run_completed_payload(
    event_id: str,
    customer_id: str,
    tenant_name: Optional[str],
    ticket: Ticket,
    run_id: str,
    serializable_state: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the full-output envelope from the sanitized final GlobalState.

    serializable_state is the AuditService._sanitize output already persisted
    to agent_runs.state_json — plain JSON-safe dicts, no Pydantic models.
    """
    hypotheses = serializable_state.get("hypotheses") or []
    return {
        "event": EVENT_RUN_COMPLETED,
        "event_id": event_id,
        "timestamp": _now_iso(),
        "tenant": _tenant_block(customer_id, tenant_name),
        "ticket": _ticket_block(ticket),
        "run": {
            "id": run_id,
            "status": "completed",
            "hypothesis_count": len(hypotheses),
        },
        "final_answer": str(serializable_state.get("final_answer") or ""),
        "findings": {
            "summary": str(serializable_state.get("final_answer") or ""),
            "hypotheses": hypotheses,
            "facts": serializable_state.get("structured_facts") or [],
            "plan": serializable_state.get("plan") or {},
            "case_status": serializable_state.get("case_status"),
            "evidence_refs": serializable_state.get("evidence_refs") or [],
        },
    }
