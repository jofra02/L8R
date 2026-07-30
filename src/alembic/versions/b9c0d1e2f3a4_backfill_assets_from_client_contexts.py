"""backfill assets from client_contexts blobs

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-07-29

Data migration: copies every component and dependency out of the active
client_contexts blobs into the relational assets / asset_relations tables.
The blob itself is left untouched — after this migration the context
adapter always overrides the inventory/dependencies keys on read, so the
stale blob copies are inert and remain available as a rollback snapshot
(downgrade of a8b9c0d1e2f3 drops the tables; the blob still holds the
pre-migration inventory).

Defensive per-item handling: a malformed component is skipped with a
warning, never aborts the migration.
"""
import json
import logging
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# Legacy Component.role -> asset type (starter definitions in
# src/assets/definitions/types/). Anything unmapped lands on "generic";
# the original role is always preserved in attributes["legacy_role"].
ROLE_TO_TYPE = {
    "firewall": "firewall",
    "router": "router",
    "switch": "switch",
    "access_point": "access_point",
    "server": "server",
    "host": "server",
    "endpoint": "endpoint",
}

PRIORITY_TO_CRITICALITY = {1: "critical", 2: "high", 3: "medium"}


def _asset_row(customer_id: str, comp: dict, final_id: str) -> dict:
    role = comp.get("role") or "unknown"
    metadata = dict(comp.get("metadata") or {})
    mcp = metadata.pop("mcp", None) or {}
    sync = mcp.get("sync") or {}

    attributes = dict(metadata)
    attributes["legacy_role"] = role

    mcp_config = None
    if mcp.get("managed"):
        mcp_config = {
            k: mcp.get(k)
            for k in ("vendor", "appliance", "device_type", "os_version",
                      "host", "port", "verify_ssl", "primary")
        }
        if sync.get("warnings"):
            mcp_config["sync_warnings"] = sync["warnings"]

    try:
        priority = int(comp.get("priority") or 1)
    except (TypeError, ValueError):
        priority = 1

    # asyncpg requires a datetime instance for timestamptz parameters
    last_synced_at = sync.get("last_synced_at")
    if isinstance(last_synced_at, str):
        try:
            last_synced_at = datetime.fromisoformat(last_synced_at.replace("Z", "+00:00"))
        except ValueError:
            last_synced_at = None

    return {
        "id": final_id,
        "customer_id": customer_id,
        "name": comp.get("ref") or final_id,
        "ref": comp.get("ref") or final_id,
        "asset_type": ROLE_TO_TYPE.get(role, "generic"),
        "type_schema_version": 1,
        "manufacturer": comp.get("vendor"),
        "status": "active",
        "criticality": PRIORITY_TO_CRITICALITY.get(priority, "low"),
        "tags": json.dumps([]),
        "attributes": json.dumps(attributes),
        "provenance": json.dumps({}),
        "managed": bool(mcp.get("managed")),
        "mcp_config": json.dumps(mcp_config) if mcp_config is not None else None,
        "sync_status": sync.get("status"),
        "sync_error": sync.get("last_error"),
        "last_synced_at": last_synced_at,
    }


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT customer_id, content FROM client_contexts WHERE is_active = true"
    )).fetchall()

    used_ids: set = {
        r[0] for r in bind.execute(sa.text("SELECT id FROM assets")).fetchall()
    }

    insert_asset = sa.text(
        "INSERT INTO assets (id, customer_id, name, ref, asset_type, "
        "type_schema_version, manufacturer, status, criticality, tags, "
        "attributes, provenance, managed, mcp_config, sync_status, sync_error, "
        "last_synced_at) VALUES (:id, :customer_id, :name, :ref, :asset_type, "
        ":type_schema_version, :manufacturer, :status, :criticality, "
        "CAST(:tags AS jsonb), CAST(:attributes AS jsonb), "
        "CAST(:provenance AS jsonb), :managed, CAST(:mcp_config AS jsonb), "
        ":sync_status, :sync_error, CAST(:last_synced_at AS timestamptz))"
    )
    insert_relation = sa.text(
        "INSERT INTO asset_relations (customer_id, source_asset_id, "
        "target_asset_id, relation_type, provenance, details) VALUES "
        "(:customer_id, :source_id, :target_id, :relation_type, 'manual', "
        "CAST(:details AS jsonb)) ON CONFLICT ON CONSTRAINT uq_asset_relation DO NOTHING"
    )

    total_assets = 0
    total_relations = 0
    for customer_id, content in rows:
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (TypeError, ValueError):
                logger.warning(f"assets backfill: unparseable blob for tenant {customer_id}, skipped")
                continue
        if not isinstance(content, dict):
            continue

        id_map: dict = {}
        seen_refs: set = set()
        for comp in content.get("inventory") or []:
            try:
                orig_id = comp.get("id")
                if not orig_id:
                    logger.warning(f"assets backfill [{customer_id}]: component without id skipped")
                    continue
                final_id = orig_id
                if final_id in used_ids:
                    final_id = f"{customer_id}--{orig_id}"
                    logger.warning(
                        f"assets backfill [{customer_id}]: id '{orig_id}' already in "
                        f"use, remapped to '{final_id}'"
                    )
                row = _asset_row(customer_id, comp, final_id)
                if row["ref"] in seen_refs:
                    row["ref"] = f"{row['ref']}--{final_id}"
                    logger.warning(
                        f"assets backfill [{customer_id}]: duplicate ref remapped to "
                        f"'{row['ref']}'"
                    )
                bind.execute(insert_asset, row)
                used_ids.add(final_id)
                seen_refs.add(row["ref"])
                id_map[orig_id] = final_id
                total_assets += 1
            except Exception as e:  # defensive: never abort the whole migration
                logger.warning(f"assets backfill [{customer_id}]: component skipped — {e}")

        for dep in content.get("dependencies") or []:
            try:
                src = id_map.get(dep.get("source_id"))
                tgt = id_map.get(dep.get("target_id"))
                if not src or not tgt:
                    logger.warning(
                        f"assets backfill [{customer_id}]: dangling dependency "
                        f"{dep.get('source_id')} -> {dep.get('target_id')} skipped"
                    )
                    continue
                bind.execute(insert_relation, {
                    "customer_id": customer_id,
                    "source_id": src,
                    "target_id": tgt,
                    "relation_type": dep.get("relation") or "depends_on",
                    "details": json.dumps(dep.get("metadata") or {}),
                })
                total_relations += 1
            except Exception as e:
                logger.warning(f"assets backfill [{customer_id}]: dependency skipped — {e}")

    logger.info(
        f"assets backfill: {total_assets} assets and {total_relations} relations "
        f"migrated from {len(rows)} active context blobs"
    )


def downgrade() -> None:
    # Intentional no-op: the pre-migration inventory still lives in the
    # client_contexts blobs; downgrading a8b9c0d1e2f3 drops the tables.
    pass
