"""Device/tenant inventory: YAML registry with Fernet-encrypted secrets."""

from .manager import InventoryManager, get_inventory, resolve_inventory_root
from .models import Device, Tenant, TenantContext
from .secrets import SecretManager
from .store import (
    DeviceExistsError,
    DeviceNotFoundError,
    EncryptionUnavailableError,
    InventoryStoreError,
    ManagedInventoryStore,
    ManualDevicesPresentError,
    TenantExistsError,
    TenantNotFoundError,
    UnmanagedDeviceError,
)

__all__ = [
    "Device",
    "DeviceExistsError",
    "DeviceNotFoundError",
    "EncryptionUnavailableError",
    "InventoryManager",
    "InventoryStoreError",
    "ManagedInventoryStore",
    "ManualDevicesPresentError",
    "SecretManager",
    "Tenant",
    "TenantContext",
    "TenantExistsError",
    "TenantNotFoundError",
    "UnmanagedDeviceError",
    "get_inventory",
    "resolve_inventory_root",
]
