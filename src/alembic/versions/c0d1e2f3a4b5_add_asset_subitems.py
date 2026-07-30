"""add asset_subitems and convert discovered child assets

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-07-30

Sub-inventory: discovered sub-entities (e.g. FortiEDR collector endpoints)
move out of the assets table into asset_subitems. Assets are curated
(human/import created); discovery only provides visibility attached to a
parent asset. The data step converts assets previously created by the
enrichment engine (created_by = 'system:enrichment' AND external_source
set) into subitems, resolving the parent through their managed_by
relation, then hard-deletes the converted asset rows (relations and audit
rows cascade). Rows without a resolvable parent are left untouched.

Downgrade drops the table without resurrecting converted assets: only dev
data exists (enrichment never ran in prod) and a sync run under the old
code regenerates them.
"""
import json
import logging
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    op.create_table(
        "asset_subitems",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(),
                  sa.ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("parent_asset_id", sa.String(),
                  sa.ForeignKey("assets.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("attributes", JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("absent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_run_id", sa.String(),
                  sa.ForeignKey("asset_sync_runs.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("promoted_asset_id", sa.String(),
                  sa.ForeignKey("assets.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("customer_id", "parent_asset_id", "source", "kind",
                            "external_id", name="uq_asset_subitem_identity"),
    )
    op.create_index("ix_asset_subitems_tenant_parent", "asset_subitems",
                    ["customer_id", "parent_asset_id"])

    bind = op.get_bind()
    children = bind.execute(sa.text(
        "SELECT id, customer_id, name, asset_type, ip_address, attributes, "
        "       external_source, external_id, created_at, updated_at "
        "FROM assets "
        "WHERE created_by = 'system:enrichment' "
        "  AND external_source IS NOT NULL AND deleted_at IS NULL"
    )).mappings().all()

    converted = []
    for child in children:
        try:
            parent = bind.execute(sa.text(
                "SELECT target_asset_id FROM asset_relations "
                "WHERE source_asset_id = :cid AND relation_type = 'managed_by' "
                "LIMIT 1"
            ), {"cid": child["id"]}).scalar()
            if parent is None:
                logger.warning(
                    "asset_subitems conversion: discovered asset %s (%s) has no "
                    "managed_by parent — left in assets untouched",
                    child["id"], child["name"])
                continue

            attrs = child["attributes"]
            if isinstance(attrs, str):
                attrs = json.loads(attrs)
            attrs = dict(attrs or {})
            state = attrs.pop("edr_state", None)
            if child["ip_address"] and "ip" not in attrs:
                attrs["ip"] = child["ip_address"]

            bind.execute(sa.text(
                "INSERT INTO asset_subitems (id, customer_id, parent_asset_id, "
                "  source, kind, external_id, name, state, attributes, absent, "
                "  first_seen_at, last_seen_at) "
                "VALUES (:id, :cust, :parent, :source, :kind, :ext, :name, "
                "  :state, CAST(:attrs AS jsonb), false, :first_seen, :last_seen)"
            ), {
                "id": uuid.uuid4().hex,
                "cust": child["customer_id"],
                "parent": parent,
                "source": child["external_source"],
                "kind": child["asset_type"],
                "ext": child["external_id"],
                "name": child["name"],
                "state": state,
                "attrs": json.dumps(attrs),
                "first_seen": child["created_at"],
                "last_seen": child["updated_at"],
            })
            converted.append(child["id"])
        except Exception:
            logger.exception(
                "asset_subitems conversion failed for asset %s — left untouched",
                child["id"])

    if converted:
        bind.execute(
            sa.text("DELETE FROM assets WHERE id = ANY(:ids)"),
            {"ids": converted},
        )
        logger.info("asset_subitems conversion: %d discovered assets converted",
                    len(converted))


def downgrade() -> None:
    op.drop_table("asset_subitems")
