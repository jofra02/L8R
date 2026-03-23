"""add inventory:read and inventory:write permissions

Revision ID: c4d5e6f7a8b9
Revises: b3f8a1c2d4e6
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b3f8a1c2d4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PERMISSIONS = [
    ("inventory:read", "inventory", "read", "View tenant inventory and context"),
    ("inventory:write", "inventory", "write", "Manage tenant inventory components, dependencies, baselines, and changes"),
]

SUPER_ADMIN_ID = "profile_super_admin"
SUPER_ADMIN_RO_ID = "profile_super_admin_readonly"
TENANT_ADMIN_ID = "profile_tenant_admin"


def upgrade() -> None:
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
    # Super Admin: both read + write
    for p in NEW_PERMISSIONS:
        pp_rows.append({"profile_id": SUPER_ADMIN_ID, "permission_id": p[0]})
    # Super Admin Readonly: read only
    pp_rows.append({"profile_id": SUPER_ADMIN_RO_ID, "permission_id": "inventory:read"})
    # Tenant Admin: both read + write
    for p in NEW_PERMISSIONS:
        pp_rows.append({"profile_id": TENANT_ADMIN_ID, "permission_id": p[0]})

    op.bulk_insert(pp_table, pp_rows)


def downgrade() -> None:
    op.execute("DELETE FROM profile_permissions WHERE permission_id IN ('inventory:read', 'inventory:write')")
    op.execute("DELETE FROM permissions WHERE id IN ('inventory:read', 'inventory:write')")
