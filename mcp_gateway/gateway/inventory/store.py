"""Write layer for admin-managed devices.

The admin API only ever writes ``devices/managed.yaml`` (list-of-devices
format). Hand-maintained device files are readable but never rewritten, so
their comments and formatting survive. All operations work on the raw YAML:
existing ``ENC(...)`` values are copied through untouched and new plaintext
tokens are encrypted before they hit disk.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .manager import resolve_inventory_root
from .secrets import SecretManager

log = logging.getLogger("gateway.inventory.store")

MANAGED_FILE = "managed.yaml"

# Serializes read-modify-write cycles within the (single) gateway process.
_WRITE_LOCK = threading.Lock()


class InventoryStoreError(Exception):
    """Base class for managed-store failures."""


class DeviceExistsError(InventoryStoreError):
    """Create with an id that already exists in any device file."""


class DeviceNotFoundError(InventoryStoreError):
    """Update/delete of an id that exists nowhere."""


class UnmanagedDeviceError(InventoryStoreError):
    """Update/delete of a device defined in a hand-maintained file."""


class EncryptionUnavailableError(InventoryStoreError):
    """A plaintext token was provided but INVENTORY_MASTER_KEY is not set."""


class TenantExistsError(InventoryStoreError):
    """Create of a tenant whose ``tenant.yaml`` already exists."""


class TenantNotFoundError(InventoryStoreError):
    """Delete of a tenant with no inventory directory."""


class ManualDevicesPresentError(InventoryStoreError):
    """Delete of a tenant whose ``devices/`` holds hand-maintained files."""


class ManagedInventoryStore:
    def __init__(self, root_dir: Optional[Path] = None, secrets: Optional[SecretManager] = None):
        self.root_dir = Path(root_dir) if root_dir else resolve_inventory_root()
        self.tenants_dir = self.root_dir / "tenants"
        self.secrets = secrets or SecretManager()

    # --- paths ---

    def _devices_dir(self, customer_id: str) -> Path:
        return self.tenants_dir / customer_id / "devices"

    def _managed_path(self, customer_id: str) -> Path:
        return self._devices_dir(customer_id) / MANAGED_FILE

    # --- raw reads ---

    def list_raw(self, customer_id: str) -> List[Dict[str, Any]]:
        """Entries of ``managed.yaml``, raw (``ENC(...)`` preserved)."""
        path = self._managed_path(customer_id)
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            return []
        if isinstance(data, dict):
            # Single-device format is valid for the loader but the store only
            # writes lists; normalize on read.
            data.setdefault("id", path.stem)
            return [data]
        return [d for d in data if isinstance(d, dict)]

    def list_manual_raw(self, customer_id: str) -> List[Dict[str, Any]]:
        """Raw entries from every hand-maintained device file (best-effort)."""
        devices_dir = self._devices_dir(customer_id)
        if not devices_dir.exists():
            return []

        entries: List[Dict[str, Any]] = []
        for device_file in sorted(devices_dir.glob("*.yaml")):
            if device_file.name.endswith(".example.yaml") or device_file.name == MANAGED_FILE:
                continue
            try:
                with open(device_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except Exception as e:
                log.error(f"Error reading device file {device_file}: {e}")
                continue
            if isinstance(data, list):
                entries.extend(d for d in data if isinstance(d, dict))
            elif isinstance(data, dict):
                data.setdefault("id", device_file.stem)
                entries.append(data)
        return entries

    def all_device_ids(self, customer_id: str) -> Dict[str, bool]:
        """Map of device id -> True when the device is admin-managed."""
        ids: Dict[str, bool] = {}
        for entry in self.list_manual_raw(customer_id):
            if entry.get("id"):
                ids[str(entry["id"])] = False
        for entry in self.list_raw(customer_id):
            if entry.get("id"):
                ids[str(entry["id"])] = True
        return ids

    # --- tenant provisioning ---

    def _tenant_dir(self, customer_id: str) -> Path:
        """Tenant directory, guaranteed to stay under ``tenants_dir``."""
        path = (self.tenants_dir / customer_id).resolve()
        if path.parent != self.tenants_dir.resolve():
            raise InventoryStoreError(f"Invalid tenant id '{customer_id}'.")
        return path

    def create_tenant(
        self, customer_id: str, name: str, description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Provision ``tenants/<cid>/`` with a minimal tenant.yaml.

        A bare pre-created directory (no tenant.yaml) is adopted rather than
        rejected, so out-of-band ``mkdir`` provisioning stays compatible.
        """
        with _WRITE_LOCK:
            tenant_dir = self._tenant_dir(customer_id)
            tenant_yaml = tenant_dir / "tenant.yaml"
            if tenant_yaml.exists():
                raise TenantExistsError(f"Tenant '{customer_id}' already exists.")

            entry: Dict[str, Any] = {
                "id": customer_id,
                "name": name,
                "context": {"critical_networks": [], "contacts": []},
            }
            if description:
                entry["description"] = description

            (tenant_dir / "devices").mkdir(parents=True, exist_ok=True)
            tmp_path = tenant_yaml.with_suffix(".yaml.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(entry, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            os.replace(tmp_path, tenant_yaml)
            return entry

    def delete_tenant(self, customer_id: str) -> None:
        """Remove ``tenants/<cid>/`` unless hand-maintained device files exist."""
        with _WRITE_LOCK:
            tenant_dir = self._tenant_dir(customer_id)
            if not tenant_dir.is_dir():
                raise TenantNotFoundError(f"Tenant '{customer_id}' has no inventory directory.")

            devices_dir = tenant_dir / "devices"
            manual = [
                p.name
                for p in sorted(devices_dir.glob("*.yaml"))
                if not p.name.endswith(".example.yaml") and p.name != MANAGED_FILE
            ] if devices_dir.is_dir() else []
            if manual:
                raise ManualDevicesPresentError(
                    f"Tenant '{customer_id}' has hand-maintained device files "
                    f"({', '.join(manual)}); remove them on the gateway host first."
                )
            shutil.rmtree(tenant_dir)

    # --- mutations ---

    def create(
        self,
        customer_id: str,
        device: Dict[str, Any],
        *,
        plaintext_token: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], List[str]]:
        with _WRITE_LOCK:
            device_id = str(device["id"])
            existing = self.all_device_ids(customer_id)
            if device_id in existing:
                raise DeviceExistsError(
                    f"Device '{device_id}' already exists"
                    f"{'' if existing[device_id] else ' in a hand-maintained file'}."
                )

            entry = self._prepare_entry(device, current=None, plaintext_token=plaintext_token)
            managed = self.list_raw(customer_id)
            managed.append(entry)
            warnings = self._enforce_single_primary(customer_id, managed, entry)
            self._write(customer_id, managed)
            return entry, warnings

    def update(
        self,
        customer_id: str,
        device_id: str,
        patch: Dict[str, Any],
        *,
        plaintext_token: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], List[str]]:
        with _WRITE_LOCK:
            managed = self.list_raw(customer_id)
            current = next((d for d in managed if str(d.get("id")) == device_id), None)
            if current is None:
                self._raise_missing(customer_id, device_id)

            merged = dict(current)
            connection_patch = patch.pop("connection", None)
            for key, value in patch.items():
                if value is not None:
                    merged[key] = value
            if connection_patch:
                connection = dict(merged.get("connection") or {})
                connection.update({k: v for k, v in connection_patch.items() if v is not None})
                merged["connection"] = connection

            entry = self._prepare_entry(merged, current=current, plaintext_token=plaintext_token)
            managed[managed.index(current)] = entry
            warnings = self._enforce_single_primary(customer_id, managed, entry)
            self._write(customer_id, managed)
            return entry, warnings

    def delete(self, customer_id: str, device_id: str) -> None:
        with _WRITE_LOCK:
            managed = self.list_raw(customer_id)
            remaining = [d for d in managed if str(d.get("id")) != device_id]
            if len(remaining) == len(managed):
                self._raise_missing(customer_id, device_id)
            self._write(customer_id, remaining)

    # --- internals ---

    def _raise_missing(self, customer_id: str, device_id: str) -> None:
        if device_id in {str(e.get("id")) for e in self.list_manual_raw(customer_id)}:
            raise UnmanagedDeviceError(
                f"Device '{device_id}' is defined in a hand-maintained file; "
                "edit that file directly (the admin API only manages managed.yaml)."
            )
        raise DeviceNotFoundError(f"Device '{device_id}' not found.")

    def _prepare_entry(
        self,
        device: Dict[str, Any],
        *,
        current: Optional[Dict[str, Any]],
        plaintext_token: Optional[str],
    ) -> Dict[str, Any]:
        entry = dict(device)
        connection = dict(entry.get("connection") or {})

        if plaintext_token is not None:
            if not self.secrets.fernet:
                raise EncryptionUnavailableError(
                    "Cannot store token: INVENTORY_MASTER_KEY is not configured."
                )
            connection["token"] = self.secrets.encrypt(plaintext_token)
        elif current is not None:
            # No new token: keep the existing ciphertext byte-identical.
            existing_token = (current.get("connection") or {}).get("token")
            if existing_token is not None:
                connection["token"] = existing_token
        entry["connection"] = connection
        return entry

    def _enforce_single_primary(
        self,
        customer_id: str,
        managed: List[Dict[str, Any]],
        entry: Dict[str, Any],
    ) -> List[str]:
        warnings: List[str] = []
        if not entry.get("primary"):
            return warnings

        for other in managed:
            if other is not entry and other.get("type") == entry.get("type") and other.get("primary"):
                other["primary"] = False

        # The registry picks the first primary in file order and hand-maintained
        # files sort before managed.yaml, so a manual primary always wins.
        for manual in self.list_manual_raw(customer_id):
            if manual.get("type") == entry.get("type") and manual.get("primary"):
                warnings.append(
                    f"Device '{manual.get('id')}' in a hand-maintained file is also marked "
                    "primary and takes precedence; remove its 'primary' flag to hand control "
                    "to the managed inventory."
                )
        return warnings

    def _write(self, customer_id: str, entries: List[Dict[str, Any]]) -> None:
        path = self._managed_path(customer_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".yaml.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write("# Managed by the gateway admin API — do not edit by hand.\n")
            yaml.safe_dump(entries, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        os.replace(tmp_path, path)
