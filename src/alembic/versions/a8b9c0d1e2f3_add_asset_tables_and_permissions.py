"""add asset inventory tables and assets permissions

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-07-29

Asset Inventory module: relational successor of the Component entries
embedded in client_contexts.content. Five tables (assets, asset_relations,
asset_definition_versions, asset_sync_runs, asset_audit_log) plus the
assets:read/write/manage/read_global permissions mapped into the three
system profiles (same pattern as f7a8b9c0d1e2).

Deliberate deviation from the sa.JSON convention: these tables use
postgresql JSONB + GIN indexes because dynamic-attribute search needs
containment operators. The deployment is Postgres-only (asyncpg DSN,
partial indexes already in use), so no portability is lost.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PERMISSIONS = [
    ("assets:read", "assets", "read",
     "View assets, relations, history and sync runs"),
    ("assets:write", "assets", "write",
     "Create, edit and soft-delete assets and relations"),
    ("assets:manage", "assets", "manage",
     "Restore, import, enrich and view sensitive asset fields"),
    ("assets:read_global", "assets", "read_global",
     "Search assets across all tenants (MSP scope)"),
]

SUPER_ADMIN_ID = "profile_super_admin"
SUPER_ADMIN_RO_ID = "profile_super_admin_readonly"
TENANT_ADMIN_ID = "profile_tenant_admin"


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(),
                  sa.ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("ref", sa.String(), nullable=False),
        sa.Column("asset_type", sa.String(), nullable=False),
        sa.Column("type_schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("manufacturer", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("serial_number", sa.String(), nullable=True, index=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True, index=True),
        sa.Column("fqdn", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("criticality", sa.String(), nullable=True),
        sa.Column("tags", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("warranty_expires", sa.Date(), nullable=True),
        sa.Column("eol_date", sa.Date(), nullable=True),
        sa.Column("attributes", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provenance", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("managed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mcp_config", JSONB(), nullable=True),
        sa.Column("sync_status", sa.String(), nullable=True),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_source", sa.String(), nullable=True),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
    )
    op.create_index("ix_assets_tenant_created", "assets", ["customer_id", "created_at"])
    op.create_index("ix_assets_tenant_type", "assets", ["customer_id", "asset_type"])
    op.create_index("ix_assets_tenant_status", "assets", ["customer_id", "status"])
    op.create_index("ix_assets_attributes_gin", "assets", ["attributes"],
                    postgresql_using="gin",
                    postgresql_ops={"attributes": "jsonb_path_ops"})
    op.create_index("ix_assets_tags_gin", "assets", ["tags"], postgresql_using="gin")
    op.create_index("uq_assets_tenant_ref", "assets", ["customer_id", "ref"],
                    unique=True, postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("uq_assets_external_identity", "assets",
                    ["customer_id", "external_source", "external_id"], unique=True,
                    postgresql_where=sa.text(
                        "external_id IS NOT NULL AND deleted_at IS NULL"))

    op.create_table(
        "asset_relations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.String(),
                  sa.ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("source_asset_id", sa.String(),
                  sa.ForeignKey("assets.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("target_asset_id", sa.String(),
                  sa.ForeignKey("assets.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("relation_type", sa.String(), nullable=False),
        sa.Column("provenance", sa.String(), nullable=False, server_default="manual"),
        sa.Column("details", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("customer_id", "source_asset_id", "target_asset_id",
                            "relation_type", name="uq_asset_relation"),
    )

    op.create_table(
        "asset_definition_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("definition_id", sa.String(), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("kind", "definition_id", "version",
                            name="uq_asset_definition_version"),
    )

    op.create_table(
        "asset_sync_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(),
                  sa.ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("asset_id", sa.String(),
                  sa.ForeignKey("assets.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("pack_id", sa.String(), nullable=False),
        sa.Column("pack_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stats", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_asset_sync_runs_tenant_asset_created", "asset_sync_runs",
                    ["customer_id", "asset_id", "created_at"])

    op.create_table(
        "asset_audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.String(),
                  sa.ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("asset_id", sa.String(),
                  sa.ForeignKey("assets.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("changes", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("sync_run_id", sa.String(),
                  sa.ForeignKey("asset_sync_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_asset_audit_tenant_asset_created", "asset_audit_log",
                    ["customer_id", "asset_id", "created_at"])

    # --- permissions seeding (pattern from f7a8b9c0d1e2) ---
    permissions_table = sa.table(
        "permissions",
        sa.column("id", sa.String),
        sa.column("resource", sa.String),
        sa.column("action", sa.String),
        sa.column("description", sa.String),
    )
    op.bulk_insert(permissions_table, [
        {"id": p[0], "resource": p[1], "action": p[2], "description": p[3]}
        for p in NEW_PERMISSIONS
    ])

    pp_table = sa.table(
        "profile_permissions",
        sa.column("profile_id", sa.String),
        sa.column("permission_id", sa.String),
    )
    pp_rows = []
    for p in NEW_PERMISSIONS:
        pp_rows.append({"profile_id": SUPER_ADMIN_ID, "permission_id": p[0]})
    pp_rows.append({"profile_id": SUPER_ADMIN_RO_ID, "permission_id": "assets:read"})
    pp_rows.append({"profile_id": SUPER_ADMIN_RO_ID, "permission_id": "assets:read_global"})
    for perm_id in ("assets:read", "assets:write", "assets:manage"):
        pp_rows.append({"profile_id": TENANT_ADMIN_ID, "permission_id": perm_id})
    op.bulk_insert(pp_table, pp_rows)


def downgrade() -> None:
    perm_ids = "('assets:read', 'assets:write', 'assets:manage', 'assets:read_global')"
    op.execute(f"DELETE FROM profile_permissions WHERE permission_id IN {perm_ids}")
    op.execute(f"DELETE FROM permissions WHERE id IN {perm_ids}")
    op.drop_table("asset_audit_log")
    op.drop_table("asset_sync_runs")
    op.drop_table("asset_definition_versions")
    op.drop_table("asset_relations")
    op.drop_table("assets")
