from typing import Dict, Any
import uuid
from datetime import datetime
from src.core.models import Ticket, TicketMode, Severity
from src.core.interfaces import IngestorInterface

_CHANGE_KW = ("change", "implement", "deploy", "provision", "install", "migrate", "upgrade")
_VALIDATION_KW = ("validation", "validate", "verify", "audit", "check", "compliance")
_INQUIRY_KW = ("inquiry", "question", "info", "information", "how", "explain")


def _detect_mode(raw: str) -> TicketMode:
    """Keyword-based first-pass mode detection from the raw type field."""
    s = raw.lower()
    if any(k in s for k in _CHANGE_KW):
        return "change"
    if any(k in s for k in _VALIDATION_KW):
        return "validation"
    if any(k in s for k in _INQUIRY_KW):
        return "inquiry"
    return "incident"


class GenericNormalizer:
    """Default normalization logic."""

    def normalize(self, raw_data: Dict[str, Any], source_id: str = "generic") -> Ticket:
        # Internal PK must always be unique: tickets_pkey is global (not
        # per-tenant), so a content hash or a source-system id as PK collides
        # on resubmission and across tenants. Source-system identity is
        # preserved in external_id instead.
        internal_id = uuid.uuid4().hex

        # Extract mode
        mode_str = raw_data.get("type", raw_data.get("mode", "incident"))
        mode: TicketMode = _detect_mode(mode_str)
        
        # Extract severity
        sev_str = raw_data.get("severity", "medium").lower()
        severity: Severity = "medium"
        if sev_str in ["low", "medium", "high", "critical"]:
            severity = sev_str
            
        # Extract text (support various common payload formats)
        subject = raw_data.get('subject', '')
        body = raw_data.get('body', '')
        fallback_text = raw_data.get('text', '')
        
        final_text = f"{subject}\n\n{body}".strip()
        if not final_text:
             final_text = fallback_text.strip()
            
        external_id = (
            raw_data.get("external_id")
            or raw_data.get("id")
            or raw_data.get("ticket_id")
        )
        return Ticket(
            id=internal_id,
            external_id=str(external_id) if external_id else None,
            mode=mode,
            text=final_text,
            severity=severity,
            source=source_id,
            timestamps={"received_at": datetime.now().isoformat()},
            raw_payload=raw_data
        )
