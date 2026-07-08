"""cascade tenant deletion: ON DELETE CASCADE on every FK to platform_tenants

Deleting a PlatformTenant previously hit an FK violation (500) as soon as the
tenant had any data (client_contexts, scopes, endpoints, ...): the FKs created
by 2be4d70ae3d7 / 732204a5c63e / a1b2c3d4e5f6 / b3f8a1c2d4e6 carry no
ON DELETE action. Recreate them all with CASCADE so ?force=true actually
cascades. Child chains (evidence_refs.ticket_id, agent_events.run_id,
tool_calls_audit.run_id, refresh_tokens.user_id) already cascade; users are
global and survive — only their tenant assignment rows go.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every table with a customer_id FK to platform_tenants
TENANT_FK_TABLES = [
    # TenantMixin tables
    "tickets",
    "agent_runs",
    "agent_events",
    "tool_calls_audit",
    "audit_logs",
    "evidence_refs",
    "client_contexts",
    "checkpoints",
    # Explicit FKs
    "tenant_endpoints",
    "capability_scopes",
    "api_keys",
    "user_tenant_profiles",
]


def _drop_tenant_fk(table: str) -> None:
    """Drop the FK on customer_id -> platform_tenants by its real name.

    The original constraints were created unnamed (Postgres auto-named them
    <table>_customer_id_fkey), so resolve the name via inspection instead of
    assuming the convention.
    """
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys(table):
        if (
            fk.get("referred_table") == "platform_tenants"
            and fk.get("constrained_columns") == ["customer_id"]
            and fk.get("name")
        ):
            op.drop_constraint(fk["name"], table, type_="foreignkey")


def upgrade() -> None:
    for table in TENANT_FK_TABLES:
        _drop_tenant_fk(table)
        op.create_foreign_key(
            f"{table}_customer_id_fkey",
            table,
            "platform_tenants",
            ["customer_id"],
            ["customer_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    for table in TENANT_FK_TABLES:
        _drop_tenant_fk(table)
        op.create_foreign_key(
            f"{table}_customer_id_fkey",
            table,
            "platform_tenants",
            ["customer_id"],
            ["customer_id"],
        )
