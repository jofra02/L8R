"""add notification_deliveries table and notifications permissions

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-27

Outbound notification system (n8n webhook): one table persisting each
delivery (payload snapshot + attempt result) so failed deliveries can be
resent from the UI, plus notifications:read / notifications:manage
permissions mapped into the three system profiles (same pattern as
e6f7a8b9c0d1).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PERMISSIONS = [
    ("notifications:read", "notifications", "read",
     "View outbound notification deliveries"),
    ("notifications:manage", "notifications", "manage",
     "Resend outbound notifications"),
]

SUPER_ADMIN_ID = "profile_super_admin"
SUPER_ADMIN_RO_ID = "profile_super_admin_readonly"
TENANT_ADMIN_ID = "profile_tenant_admin"


def upgrade() -> None:
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(),
                  sa.ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("event_type", sa.String(), nullable=False, index=True),
        sa.Column("ticket_id", sa.String(),
                  sa.ForeignKey("tickets.id", ondelete="CASCADE"),
                  nullable=True, index=True),
        sa.Column("run_id", sa.String(),
                  sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
                  nullable=True, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False,
                  server_default="pending", index=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notification_deliveries_tenant_created",
                    "notification_deliveries", ["customer_id", "created_at"])

    # --- permissions seeding (pattern from e6f7a8b9c0d1) ---
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
    pp_rows.append({"profile_id": SUPER_ADMIN_RO_ID, "permission_id": "notifications:read"})
    for p in NEW_PERMISSIONS:
        pp_rows.append({"profile_id": TENANT_ADMIN_ID, "permission_id": p[0]})
    op.bulk_insert(pp_table, pp_rows)


def downgrade() -> None:
    op.execute(
        "DELETE FROM profile_permissions WHERE permission_id IN "
        "('notifications:read', 'notifications:manage')"
    )
    op.execute(
        "DELETE FROM permissions WHERE id IN "
        "('notifications:read', 'notifications:manage')"
    )
    op.drop_table("notification_deliveries")
