"""Appliance pack discovery and loading.

Packs are organized as ``vendors/<vendor>/<appliance>/<version>/`` — a vendor
is a manufacturer (fortinet, cisco, paloalto), each of its appliances/products
(fortigate, fortianalyzer, ios_xe, panos, ...) can ship several firmware/OS
versions, and each version is a self-contained pack:

    vendors/<vendor>/<appliance>/<version>/
        manifest.yaml     # required — see ApplianceManifest for the schema
        specs/<group>/*.json  # OpenAPI/Swagger specs, one sub-server per group
        hooks.py          # optional appliance-specific transforms

Multiple versions of the same appliance mount concurrently; they share the
``device_type`` (and therefore the tenant inventory) but each carries its own
tool prefix (e.g. ``fgt74``, ``fgt76``) so tool names never collide.

``hooks.py`` may expose:
- ``SPEC_FIXES``: list of ``(spec: dict) -> dict`` callables run after the
  generic schema fixes.
- ``PARAMETER_DOC_APPENDS``: ``{param_name: help_text}`` appended to matching
  parameter descriptions in every operation.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

log = logging.getLogger("gateway.vendors")

DEFAULT_DEVICE_PARAM_DESCRIPTION = (
    "Optional: Name of the target device in inventory. Defaults to primary."
)


class ApplianceManifest(BaseModel):
    """Schema of ``vendors/<vendor>/<appliance>/<version>/manifest.yaml``."""

    vendor: str = Field(..., description="Vendor slug (matches the grandparent directory name)")
    name: str = Field(..., description="Appliance/product slug (matches the parent directory name)")
    version: str = Field(
        ..., description="Firmware/OS version covered by this pack (matches the directory name)"
    )
    display_name: str = Field(..., description="Human readable server name")
    prefix: str = Field(..., description="Mount prefix — first token of every tool name")
    device_type: str = Field(..., description="Inventory device type served by this pack")
    auth: str = Field("bearer_header", description="Auth strategy name (see gateway/auth.py)")
    spec_glob: str = Field("*.json", description="Glob for spec files inside each group dir")
    name_strips: List[str] = Field(
        default_factory=list,
        description="Substrings removed (in order) from a spec filename to build its mount name",
    )
    sanitizer_stopwords: List[str] = Field(
        default_factory=list,
        description="Filler tokens the operationId sanitizer may drop",
    )
    inventory_tool: bool = Field(
        False, description="Register a <prefix>_get_inventory_tree discovery tool"
    )
    device_param_description: str = Field(
        DEFAULT_DEVICE_PARAM_DESCRIPTION,
        description="Description of the injected 'device' routing header parameter",
    )
    http_timeout: Optional[float] = Field(
        None,
        description="Per-pack read-timeout override in seconds; falls back to GATEWAY_HTTP_TIMEOUT",
    )
    http_connect_timeout: Optional[float] = Field(
        None,
        description="Per-pack connect-timeout override in seconds; falls back to GATEWAY_HTTP_CONNECT_TIMEOUT",
    )


class AppliancePack:
    """A loaded appliance pack: manifest + paths + optional hooks."""

    def __init__(self, manifest: ApplianceManifest, root: Path):
        self.manifest = manifest
        self.root = root
        self.specs_dir = root / "specs"
        self.spec_fixes: List[Callable[[dict], dict]] = []
        self.parameter_doc_appends: Dict[str, str] = {}
        self._load_hooks()

    def _load_hooks(self) -> None:
        hooks_path = self.root / "hooks.py"
        if not hooks_path.exists():
            return

        version_label = self.manifest.version.replace(".", "_")
        spec = importlib.util.spec_from_file_location(
            f"vendors.{self.manifest.vendor}.{self.manifest.name}.{version_label}.hooks",
            hooks_path,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.spec_fixes = list(getattr(module, "SPEC_FIXES", []))
        self.parameter_doc_appends = dict(getattr(module, "PARAMETER_DOC_APPENDS", {}))
        log.info(
            f"Pack '{self.qualified_name}': loaded {len(self.spec_fixes)} spec fixes, "
            f"{len(self.parameter_doc_appends)} parameter doc appends from hooks.py"
        )

    # Convenience pass-throughs
    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def vendor(self) -> str:
        return self.manifest.vendor

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def qualified_name(self) -> str:
        return f"{self.manifest.vendor}/{self.manifest.name}/{self.manifest.version}"

    # Alias used by the catalog partitioning contract (app-side pack_key payload).
    @property
    def pack_key(self) -> str:
        return self.qualified_name

    @property
    def prefix(self) -> str:
        return self.manifest.prefix

    def spec_mount_name(self, spec_path: Path, group_name: str) -> str:
        """Derive the mount name of a spec file (the third token of tool names).

        NAME-FREEZE: replicates the original fgt_mcp logic exactly —
        apply name_strips in order, '-' -> '_', then strip a leading
        '<group>_' prefix.
        """
        safe_name = spec_path.stem
        for strip in self.manifest.name_strips:
            safe_name = safe_name.replace(strip, "")
        safe_name = safe_name.replace("-", "_")

        if safe_name.startswith(f"{group_name}_"):
            safe_name = safe_name[len(group_name) + 1:]

        return safe_name


def load_appliance_pack(pack_dir: Path) -> Optional[AppliancePack]:
    """Load one appliance pack from ``vendors/<vendor>/<appliance>/<version>/``."""
    manifest_path = pack_dir / "manifest.yaml"
    if not manifest_path.exists():
        return None

    with open(manifest_path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = yaml.safe_load(f) or {}

    data.setdefault("vendor", pack_dir.parent.parent.name)
    data.setdefault("name", pack_dir.parent.name)
    data.setdefault("version", pack_dir.name)
    manifest = ApplianceManifest(**data)
    return AppliancePack(manifest, pack_dir)


def discover_packs(vendors_root: Path) -> List[AppliancePack]:
    """Load every appliance pack under ``vendors/<vendor>/<appliance>/<version>/``.

    Sorted by vendor, appliance, then version so mount order (and therefore any
    name collision resolution) is deterministic.
    """
    packs: List[AppliancePack] = []
    if not vendors_root.exists():
        log.warning(f"Vendors directory not found: {vendors_root}")
        return packs

    for vendor_dir in sorted(p for p in vendors_root.iterdir() if p.is_dir()):
        appliance_dirs = sorted(p for p in vendor_dir.iterdir() if p.is_dir())
        if not appliance_dirs:
            log.warning(f"Vendor '{vendor_dir.name}' has no appliance directories — skipping")
            continue

        for appliance_dir in appliance_dirs:
            if (appliance_dir / "manifest.yaml").exists():
                log.error(
                    f"Unversioned pack layout at '{vendor_dir.name}/{appliance_dir.name}': "
                    f"move it to vendors/{vendor_dir.name}/{appliance_dir.name}/<version>/ — skipping"
                )
                continue

            version_dirs = sorted(p for p in appliance_dir.iterdir() if p.is_dir())
            if not version_dirs:
                log.warning(
                    f"Appliance '{vendor_dir.name}/{appliance_dir.name}' has no version "
                    f"directories — skipping"
                )
                continue

            for pack_dir in version_dirs:
                label = f"{vendor_dir.name}/{appliance_dir.name}/{pack_dir.name}"
                try:
                    pack = load_appliance_pack(pack_dir)
                    if pack:
                        packs.append(pack)
                    else:
                        log.warning(f"Skipping '{label}': no manifest.yaml")
                except Exception as e:
                    log.error(f"Failed to load pack '{label}': {e}")

    return packs
