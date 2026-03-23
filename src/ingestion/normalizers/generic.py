from typing import Dict, Any
import hashlib
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
        # Generate stable ID if not present
        raw_id = str(raw_data.get("id") or raw_data.get("ticket_id") or "")
        if not raw_id:
            raw_id = hashlib.md5(str(raw_data).encode()).hexdigest()

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
            
        return Ticket(
            id=raw_id,
            mode=mode,
            text=final_text,
            severity=severity,
            source=source_id,
            timestamps={"received_at": datetime.now().isoformat()},
            raw_payload=raw_data
        )
