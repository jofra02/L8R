"""add global product catalog and assets.product_name

Revision ID: d2e3f4a5b6c7
Revises: c0d1e2f3a4b5
Create Date: 2026-07-30

Adds the commercial product name to assets ("FortiGate", "ESXi", ...),
complementary to the free-form model column. Values are constrained to a
new global (non-tenant) asset_products catalog managed via the API; the
asset column stays a denormalized string (no FK) — renames propagate via
bulk UPDATE and deletes are blocked while the name is in use.

Seeds the asset_products:manage permission to profile_super_admin ONLY:
catalog renames/deletes ripple across every tenant, so tenant admins must
not hold it (same stance as tenants:manage).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PERMISSIONS = [
    ("asset_products:manage", "asset_products", "manage",
     "Manage the global product catalog (create, rename, delete)"),
]

SUPER_ADMIN_ID = "profile_super_admin"


def upgrade() -> None:
    op.add_column("assets", sa.Column("product_name", sa.String(), nullable=True))
    op.create_index("ix_assets_product_name", "assets", ["product_name"])

    op.create_table(
        "asset_products",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
    )
    op.create_index("uq_asset_products_name_lower", "asset_products",
                    [sa.text("lower(name)")], unique=True)

    # --- permissions seeding (pattern from a8b9c0d1e2f3) ---
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
    op.bulk_insert(pp_table, [
        {"profile_id": SUPER_ADMIN_ID, "permission_id": p[0]}
        for p in NEW_PERMISSIONS
    ])


def downgrade() -> None:
    op.execute(
        "DELETE FROM profile_permissions WHERE permission_id = 'asset_products:manage'")
    op.execute("DELETE FROM permissions WHERE id = 'asset_products:manage'")
    op.drop_index("uq_asset_products_name_lower", table_name="asset_products")
    op.drop_table("asset_products")
    op.drop_index("ix_assets_product_name", table_name="assets")
    op.drop_column("assets", "product_name")
