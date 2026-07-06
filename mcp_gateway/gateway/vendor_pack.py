"""Vendor pack discovery and loading.

A vendor pack is a directory under ``vendors/`` with:

    vendors/<name>/
        manifest.yaml     # required — see VendorManifest for the schema
        specs/<group>/*.json  # OpenAPI/Swagger specs, one sub-server per group
        hooks.py          # optional vendor-specific transforms

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


class VendorManifest(BaseModel):
    """Schema of ``vendors/<name>/manifest.yaml``."""

    name: str = Field(..., description="Vendor slug (matches the directory name)")
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


class VendorPack:
    """A loaded vendor pack: manifest + paths + optional hooks."""

    def __init__(self, manifest: VendorManifest, root: Path):
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

        spec = importlib.util.spec_from_file_location(
            f"vendors.{self.manifest.name}.hooks", hooks_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.spec_fixes = list(getattr(module, "SPEC_FIXES", []))
        self.parameter_doc_appends = dict(getattr(module, "PARAMETER_DOC_APPENDS", {}))
        log.info(
            f"Vendor '{self.manifest.name}': loaded {len(self.spec_fixes)} spec fixes, "
            f"{len(self.parameter_doc_appends)} parameter doc appends from hooks.py"
        )

    # Convenience pass-throughs
    @property
    def name(self) -> str:
        return self.manifest.name

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


def load_vendor_pack(pack_dir: Path) -> Optional[VendorPack]:
    manifest_path = pack_dir / "manifest.yaml"
    if not manifest_path.exists():
        return None

    with open(manifest_path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = yaml.safe_load(f) or {}

    data.setdefault("name", pack_dir.name)
    manifest = VendorManifest(**data)
    return VendorPack(manifest, pack_dir)


def discover_vendor_packs(vendors_root: Path) -> List[VendorPack]:
    """Load every valid vendor pack under ``vendors_root``, sorted by name."""
    packs: List[VendorPack] = []
    if not vendors_root.exists():
        log.warning(f"Vendors directory not found: {vendors_root}")
        return packs

    for pack_dir in sorted(p for p in vendors_root.iterdir() if p.is_dir()):
        try:
            pack = load_vendor_pack(pack_dir)
            if pack:
                packs.append(pack)
            else:
                log.warning(f"Skipping '{pack_dir.name}': no manifest.yaml")
        except Exception as e:
            log.error(f"Failed to load vendor pack '{pack_dir.name}': {e}")

    return packs
