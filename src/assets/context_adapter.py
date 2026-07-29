"""Compatibility adapter: assemble ClientContext inventory from asset tables.

The relational assets/asset_relations tables are the source of truth for
components and dependencies. The five ClientContext consumers
(assessment_service.create_run, engineer query_client_db, pack_matching,
topology seeding, seed scripts) keep reading the exact pre-migration
Pydantic shape — this module rebuilds it, including the metadata["mcp"]
block that pack_matching and assessments inspect. Field provenance is
NOT exposed here.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from sqlalchemy import select

from src.core.orm import AssetORM, AssetRelationORM

logger = logging.getLogger(__name__)

# asset_type -> legacy ComponentRole fallback (used only when the asset has
# no attributes["legacy_role"]). Values must be valid ComponentRole literals.
TYPE_TO_ROLE = {
    "firewall": "firewall",
    "router": "router",
    "switch": "switch",
    "access_point": "access_point",
    "server": "server",
    "endpoint": "endpoint",
    "edr_console": "appliance",
    "generic": "unknown",
}

CRITICALITY_TO_PRIORITY = {"critical": 1, "high": 2, "medium": 3, "low": 4}
PRIORITY_TO_CRITICALITY = {1: "critical", 2: "high", 3: "medium"}

# Keep in sync with the Literal in src/core/models.py — hydration fails on
# values outside it.
_VALID_ROLES = frozenset({
    "firewall", "router", "switch", "loadbalancer", "gateway", "access_point",
    "server", "host", "hypervisor", "node", "cluster", "storage", "nas", "san",
    "vm", "container", "pod", "instance", "function",
    "service", "process", "application", "database", "api", "queue",
    "subnet", "network", "endpoint", "user", "dns_name", "url",
    "appliance", "controller", "unknown",
})


def component_role(asset: AssetORM) -> str:
    legacy = (asset.attributes or {}).get("legacy_role")
    if legacy in _VALID_ROLES:
        return legacy
    role = TYPE_TO_ROLE.get(asset.asset_type, "unknown")
    return role if role in _VALID_ROLES else "unknown"


def asset_to_component_dict(asset: AssetORM) -> Dict[str, Any]:
    """Component-shaped dict (id/ref/role/vendor/priority/metadata)."""
    metadata = {
        k: v for k, v in (asset.attributes or {}).items() if k != "legacy_role"
    }
    if asset.managed and asset.mcp_config:
        cfg = dict(asset.mcp_config)
        warnings = cfg.pop("sync_warnings", [])
        sync: Dict[str, Any] = {
            "status": asset.sync_status,
            "last_error": asset.sync_error,
            "warnings": warnings,
        }
        if asset.last_synced_at is not None:
            sync["last_synced_at"] = asset.last_synced_at.isoformat()
        metadata["mcp"] = {"managed": True, **cfg, "sync": sync}

    return {
        "id": asset.id,
        "ref": asset.ref,
        "role": component_role(asset),
        "vendor": asset.manufacturer,
        "priority": CRITICALITY_TO_PRIORITY.get(asset.criticality or "", 4),
        "metadata": metadata,
    }


def relation_to_dependency_dict(rel: AssetRelationORM) -> Dict[str, Any]:
    return {
        "source_id": rel.source_asset_id,
        "target_id": rel.target_asset_id,
        "relation": rel.relation_type,
        "metadata": rel.details or {},
    }


async def assemble_inventory(
    session, customer_id: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (components, dependencies) dicts for the tenant's live assets."""
    assets = (
        await session.execute(
            select(AssetORM)
            .where(AssetORM.customer_id == customer_id,
                   AssetORM.deleted_at.is_(None))
            .order_by(AssetORM.created_at)
        )
    ).scalars().all()
    relations = (
        await session.execute(
            select(AssetRelationORM)
            .where(AssetRelationORM.customer_id == customer_id)
            .order_by(AssetRelationORM.id)
        )
    ).scalars().all()

    live_ids = {a.id for a in assets}
    components = [asset_to_component_dict(a) for a in assets]
    dependencies = [
        relation_to_dependency_dict(r)
        for r in relations
        if r.source_asset_id in live_ids and r.target_asset_id in live_ids
    ]
    return components, dependencies
