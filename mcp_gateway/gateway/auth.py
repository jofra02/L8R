"""Per-vendor authentication strategies.

A vendor pack declares its auth style in ``manifest.yaml`` (``auth: bearer_header``).
The strategy turns a device's ``connection`` dict into HTTP headers, both for
the client defaults (primary device) and when a request is re-routed to
another device. Adding a new style is one class + one registry entry.
"""

from __future__ import annotations

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


_STRATEGIES: Dict[str, AuthStrategy] = {
    "bearer_header": BearerHeaderAuth(),
}


def get_auth_strategy(name: str) -> AuthStrategy:
    try:
        return _STRATEGIES[name]
    except KeyError:
        raise ValueError(
            f"Unknown auth strategy '{name}'. Available: {sorted(_STRATEGIES)}"
        ) from None
