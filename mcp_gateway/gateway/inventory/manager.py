"""Inventory manager — loads tenant and device YAML from ``inventory/``.

Layout: ``inventory/tenants/<customer_id>/tenant.yaml`` plus
``inventory/tenants/<customer_id>/devices/*.yaml`` (single device dict or a
list of devices per file). ``ENC(...)`` values are decrypted on load.
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Optional

import yaml

from .models import Device, Tenant
from .secrets import SecretManager

log = logging.getLogger("gateway.inventory")

# Default location: mcp_gateway/inventory
INVENTORY_ROOT = Path(__file__).resolve().parents[2] / "inventory"


class InventoryManager:
    def __init__(self, root_dir: Path = INVENTORY_ROOT):
        self.root_dir = root_dir
        self.tenants_dir = self.root_dir / "tenants"
        self.secrets = SecretManager()  # Key comes from INVENTORY_MASTER_KEY

    def _decrypt_recursive(self, data: Any) -> Any:
        """Walk dicts/lists and decrypt every ``ENC(...)`` string in place."""
        if isinstance(data, dict):
            return {k: self._decrypt_recursive(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._decrypt_recursive(item) for item in data]
        elif isinstance(data, str):
            if self.secrets.is_encrypted(data):
                return self.secrets.decrypt(data)
            return data
        else:
            return data

    def get_tenant(self, customer_id: str) -> Tenant:
        """Load ``tenant.yaml`` for a customer_id."""
        tenant_path = self.tenants_dir / customer_id / "tenant.yaml"
        if not tenant_path.exists():
            raise FileNotFoundError(f"Tenant configuration not found at {tenant_path}")

        with open(tenant_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        data = self._decrypt_recursive(data)

        if "id" not in data:
            data["id"] = customer_id

        return Tenant(**data)

    def get_devices(self, customer_id: str, device_type: Optional[str] = None) -> List[Device]:
        """Load all devices for a customer_id, optionally filtered by device type."""
        devices_dir = self.tenants_dir / customer_id / "devices"
        if not devices_dir.exists():
            return []

        devices: List[Device] = []
        for device_file in sorted(devices_dir.glob("*.yaml")):
            if device_file.name.endswith(".example.yaml"):
                continue  # Anonymized samples shipped in git, never live config
            try:
                with open(device_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                data = self._decrypt_recursive(data)

                # Multi-device file: a YAML list of device dicts (ids required)
                if isinstance(data, list):
                    for item in data:
                        try:
                            device = Device(**item)
                            if device_type and device.type != device_type:
                                continue
                            devices.append(device)
                        except Exception as e:
                            log.error(f"Error loading device item in {device_file}: {e}")

                # Single-device file: id defaults to the file stem
                elif isinstance(data, dict):
                    if "id" not in data:
                        data["id"] = device_file.stem

                    device = Device(**data)

                    if device_type and device.type != device_type:
                        continue

                    devices.append(device)
            except Exception as e:
                # Skip broken files without crashing the whole inventory load
                log.error(f"Error loading device file {device_file}: {e}")
                continue

        return devices


@lru_cache(maxsize=1)
def get_inventory() -> InventoryManager:
    return InventoryManager()
