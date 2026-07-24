"""Evidence sanitization: secret redaction, size caps, injection fencing.

Everything collected from a device is untrusted input. Before persistence we
redact secret material; before any LLM sees evidence we fence it with a
per-call random boundary so device-originated text cannot masquerade as
instructions.
"""

from __future__ import annotations

import json
import re
import secrets
from typing import Any, Dict, List, Tuple

REDACTED = "[REDACTED]"

# Secret-bearing patterns that appear inside FortiOS payloads regardless of
# the field names a definition lists (defense in depth).
_PATTERNS = [
    # FortiOS encrypted secrets: ENC <base64>
    re.compile(r"ENC\s+[A-Za-z0-9+/=]{16,}"),
    # PEM blocks (private keys, certs bundled with keys)
    re.compile(r"-----BEGIN [A-Z ]+-----.*?-----END [A-Z ]+-----", re.DOTALL),
    # CLI-style secret assignments
    re.compile(r"(set\s+(?:password|passwd|private-key|psksecret|secret)\s+).+", re.IGNORECASE),
]

# Field names always redacted, in addition to the per-step YAML `sanitize` list
_ALWAYS_REDACT_FIELDS = {
    "password", "passwd", "secret", "psksecret", "private-key", "privatekey",
    "api-key", "apikey", "token", "auth-pwd", "passphrase",
}


def redact_fields(data: Any, field_names: List[str]) -> Any:
    """Recursively redact named fields (case-insensitive) in dicts/lists."""
    targets = {f.lower() for f in field_names} | _ALWAYS_REDACT_FIELDS

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: (REDACTED if k.lower() in targets and node[k] not in (None, "", REDACTED)
                    else walk(node[k]))
                for k in node
            }
        if isinstance(node, list):
            return [walk(i) for i in node]
        return node

    return walk(data)


def redact_patterns(text: str) -> str:
    for pat in _PATTERNS:
        text = pat.sub(lambda m: (m.group(1) + REDACTED) if m.lastindex else REDACTED, text)
    return text


def sanitize_payload(raw: Any, field_names: List[str], max_bytes: int) -> Tuple[Any, bool, int]:
    """Full sanitization pipeline for a collected payload.

    Returns (sanitized_payload, truncated, size_bytes). Structured payloads
    get field-level redaction; everything gets pattern redaction; oversized
    payloads are truncated to ``max_bytes`` (flagged, never silently).
    """
    parsed = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            parsed = raw

    if isinstance(parsed, (dict, list)):
        cleaned: Any = redact_fields(parsed, field_names)
        serialized = json.dumps(cleaned, default=str)
        serialized = redact_patterns(serialized)
        size = len(serialized.encode("utf-8"))
        if size > max_bytes:
            return serialized[:max_bytes], True, size
        try:
            return json.loads(serialized), False, size
        except json.JSONDecodeError:
            # Pattern redaction broke JSON syntax (secret spanned tokens)
            return serialized, False, size

    text = redact_patterns(str(parsed))
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        return text[:max_bytes], True, size
    return text, False, size


def fence_evidence(evidence: Dict[str, Any]) -> Tuple[str, str]:
    """Wrap evidence blocks in per-call random boundaries for LLM prompts.

    Returns (fenced_text, boundary_token). Any occurrence of the boundary
    inside the evidence itself is stripped, so device output can never close
    or forge a fence.
    """
    token = secrets.token_hex(6)
    blocks = []
    for step_id, payload in evidence.items():
        body = json.dumps(payload, indent=2, default=str) if not isinstance(payload, str) else payload
        body = body.replace(token, "")
        blocks.append(f"<<EVIDENCE {token} step={step_id}>>\n{body}\n<<END {token}>>")
    return "\n\n".join(blocks), token
