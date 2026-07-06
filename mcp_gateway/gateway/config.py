"""Gateway configuration and per-vendor device registry.

The gateway serves one tenant per process, selected by ``ACTIVE_CUSTOMER_ID``
(``ACTIVE_TENANT`` is accepted as a legacy fallback). The customer_id matches
the tenant ids used by support_ai_agent (e.g. ``fake_client``).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv

from .inventory.manager import get_inventory
from .inventory.models import Device

GATEWAY_ROOT = Path(__file__).resolve().parents[1]

# Load mcp_gateway/.env (harmless no-op when absent, e.g. inside the container
# where everything arrives via compose environment). Real environment variables
# take precedence over the file.
load_dotenv(dotenv_path=GATEWAY_ROOT / ".env", override=False, encoding="utf-8")

log = logging.getLogger("gateway.config")


class GatewaySettings:
    """Process-level settings read from the environment."""

    def __init__(self) -> None:
        self.active_customer_id: str = (
            os.getenv("ACTIVE_CUSTOMER_ID") or os.getenv("ACTIVE_TENANT") or "fake_client"
        )
        self.http_timeout: float = float(os.getenv("GATEWAY_HTTP_TIMEOUT", "10"))
        self.http_connect_timeout: float = float(os.getenv("GATEWAY_HTTP_CONNECT_TIMEOUT", "5"))


@lru_cache(maxsize=1)
def get_settings() -> GatewaySettings:
    return GatewaySettings()


class DeviceRegistry:
    """All inventory devices of one type for the active customer.

    Holds the lookup map used for per-request routing and designates the
    primary device (explicit ``primary: true`` flag, else the first device in
    file/list order) used when a tool call carries no ``device`` header.
    """

    def __init__(self, customer_id: str, device_type: str) -> None:
        self.customer_id = customer_id
        self.device_type = device_type
        self.devices: Dict[str, Device] = {}
        self.primary: Optional[Device] = None

        inventory = get_inventory()
        try:
            device_list = inventory.get_devices(customer_id, device_type=device_type)
        except Exception as e:
            log.error(f"Failed to load inventory for customer '{customer_id}': {e}")
            raise

        if not device_list:
            log.warning(
                f"No '{device_type}' devices found for customer '{customer_id}'. "
                "Tools will load but calls without routing will fail."
            )
            return

        self.devices = {d.id: d for d in device_list}
        self.primary = next((d for d in device_list if d.primary), device_list[0])
        log.info(
            f"Loaded {len(self.devices)} '{device_type}' devices for customer "
            f"'{customer_id}' (primary: {self.primary.id})."
        )

    def get(self, device_id: str) -> Optional[Device]:
        return self.devices.get(device_id)

    def resolve_primary_connection(self) -> Dict[str, object]:
        """Connection dict of the primary device with env-var indirection applied.

        ``host_env_var`` / ``token_env_var`` let an inventory entry defer the
        actual value to the environment.
        """
        if not self.primary:
            return {}

        conn = dict(self.primary.connection)

        if "host_env_var" in conn:
            conn["host"] = os.getenv(str(conn["host_env_var"]), conn.get("host", ""))
        if "token_env_var" in conn:
            conn["token"] = os.getenv(str(conn["token_env_var"]), "")

        return conn
