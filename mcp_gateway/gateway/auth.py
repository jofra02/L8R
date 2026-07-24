"""Per-vendor authentication strategies.

A vendor pack declares its auth style in ``manifest.yaml`` (``auth: bearer_header``).
The strategy turns a device's ``connection`` dict into HTTP headers, both for
the client defaults (primary device) and when a request is re-routed to
another device. Adding a new style is one class + one registry entry.
"""

from __future__ import annotations

import base64
from typing import Dict, Protocol


class AuthStrategy(Protocol):
    def headers(self, connection: Dict[str, object]) -> Dict[str, str]:
        """Build the auth headers for a device connection."""
        ...


class BearerHeaderAuth:
    """``Authorization: Bearer <token>`` from ``connection.token`` (FortiOS style)."""

    def headers(self, connection: Dict[str, object]) -> Dict[str, str]:
        token = connection.get("token", "")
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}


class BasicHeaderAuth:
    """``Authorization: Basic base64(token)`` from ``connection.token``.

    The token holds the raw ``user:password`` pair — for FortiEDR multi-tenancy
    that is ``organization\\api_user:password`` (org as a backslash prefix, e.g.
    ``Acme\\apiuser:secret``; the ``user@organization`` form is rejected).
    The API user must hold the REST API role. Sent as HTTP Basic on every call:
    FortiEDR's ``X-Auth-Token`` is bound to the TCP session (60s idle / 4h max),
    so per-call Basic is the reliable path. Fernet-encrypted at rest like any
    other token.
    """

    def headers(self, connection: Dict[str, object]) -> Dict[str, str]:
        token = str(connection.get("token", "") or "")
        if not token:
            return {}
        encoded = base64.b64encode(token.encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}


_STRATEGIES: Dict[str, AuthStrategy] = {
    "bearer_header": BearerHeaderAuth(),
    "basic_header": BasicHeaderAuth(),
}


def get_auth_strategy(name: str) -> AuthStrategy:
    try:
        return _STRATEGIES[name]
    except KeyError:
        raise ValueError(
            f"Unknown auth strategy '{name}'. Available: {sorted(_STRATEGIES)}"
        ) from None
