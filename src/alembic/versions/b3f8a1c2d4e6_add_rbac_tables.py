"""add RBAC tables (users, permissions, profiles, refresh_tokens) and seed data

Revision ID: b3f8a1c2d4e6
Revises: a1b2c3d4e5f6
Create Date: 2026-03-23

"""
from typing import Sequence, Union
import uuid
import secrets
import hashlib

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b3f8a1c2d4e6"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- Permission catalog ---
PERMISSIONS = [
    ("tickets:read", "tickets", "read", "View tickets"),
    ("tickets:write", "tickets", "write", "Create and update tickets"),
    ("runs:read", "runs", "read", "View agent runs"),
    ("evidence:read", "evidence", "read", "View evidence snapshots"),
    ("audit:read", "audit", "read", "View audit logs"),
    ("keys:read", "keys", "read", "View API keys"),
    ("keys:manage", "keys", "manage", "Create, revoke, and rotate API keys"),
    ("users:read", "users", "read", "View user accounts"),
    ("users:manage", "users", "manage", "Create, update, and deactivate users"),
    ("profiles:read", "profiles", "read", "View profiles and permissions"),
    ("profiles:manage", "profiles", "manage", "Create, update, and delete profiles"),
    ("tenants:read", "tenants", "read", "View tenant information"),
    ("tenants:manage", "tenants", "manage", "Create and manage tenants"),
]

ALL_PERM_IDS = [p[0] for p in PERMISSIONS]
READ_PERM_IDS = [p[0] for p in PERMISSIONS if p[2] == "read"]

# --- System profiles ---
SUPER_ADMIN_ID = "profile_super_admin"
SUPER_ADMIN_RO_ID = "profile_super_admin_readonly"
TENANT_ADMIN_ID = "profile_tenant_admin"

TENANT_ADMIN_PERMS = [
    p for p in ALL_PERM_IDS if p not in ("tenants:manage", "profiles:manage")
]


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # --- permissions ---
    op.create_table(
        "permissions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("resource", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- profiles ---
    op.create_table(
        "profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # --- profile_permissions (junction) ---
    op.create_table(
        "profile_permissions",
        sa.Column("profile_id", sa.String(), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_id", sa.String(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False),
        sa.PrimaryKeyConstraint("profile_id", "permission_id"),
    )

    # --- user_tenant_profiles ---
    op.create_table(
        "user_tenant_profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.String(), sa.ForeignKey("platform_tenants.customer_id"), nullable=False),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "customer_id", name="uq_user_tenant_profile"),
    )
    op.create_index("ix_user_tenant_profiles_customer", "user_tenant_profiles", ["customer_id"])

    # --- refresh_tokens ---
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    # --- Extend api_keys with RBAC columns ---
    op.add_column("api_keys", sa.Column("profile_id", sa.String(), sa.ForeignKey("profiles.id"), nullable=True))
    op.add_column("api_keys", sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True))

    # ========== SEED DATA ==========

    # 1. Permissions
    permissions_table = sa.table(
        "permissions",
        sa.column("id", sa.String),
        sa.column("resource", sa.String),
        sa.column("action", sa.String),
        sa.column("description", sa.String),
    )
    op.bulk_insert(permissions_table, [
        {"id": p[0], "resource": p[1], "action": p[2], "description": p[3]}
        for p in PERMISSIONS
    ])

    # 2. System profiles
    profiles_table = sa.table(
        "profiles",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("is_system", sa.Boolean),
    )
    op.bulk_insert(profiles_table, [
        {"id": SUPER_ADMIN_ID, "name": "Super Admin", "description": "Full system control across all tenants", "is_system": True},
        {"id": SUPER_ADMIN_RO_ID, "name": "Super Admin Readonly", "description": "Read-only access across all tenants", "is_system": True},
        {"id": TENANT_ADMIN_ID, "name": "Tenant Admin", "description": "Full control within assigned tenants", "is_system": True},
    ])

    # 3. Profile <-> Permission mappings
    pp_table = sa.table(
        "profile_permissions",
        sa.column("profile_id", sa.String),
        sa.column("permission_id", sa.String),
    )
    pp_rows = []
    for perm_id in ALL_PERM_IDS:
        pp_rows.append({"profile_id": SUPER_ADMIN_ID, "permission_id": perm_id})
    for perm_id in READ_PERM_IDS:
        pp_rows.append({"profile_id": SUPER_ADMIN_RO_ID, "permission_id": perm_id})
    for perm_id in TENANT_ADMIN_PERMS:
        pp_rows.append({"profile_id": TENANT_ADMIN_ID, "permission_id": perm_id})
    op.bulk_insert(pp_table, pp_rows)

    # 4. Bootstrap super admin user
    bootstrap_password = secrets.token_urlsafe(16)
    try:
        import bcrypt
        password_hash = bcrypt.hashpw(bootstrap_password.encode(), bcrypt.gensalt()).decode()
    except ImportError:
        password_hash = hashlib.sha256(bootstrap_password.encode()).hexdigest()
        print("\n" + "=" * 60)
        print("WARNING: bcrypt not installed. Using SHA-256 fallback.")
        print("Install bcrypt before production use: pip install bcrypt")
        print("=" * 60)

    admin_id = str(uuid.uuid4())
    users_table = sa.table(
        "users",
        sa.column("id", sa.String),
        sa.column("email", sa.String),
        sa.column("display_name", sa.String),
        sa.column("password_hash", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("is_platform_admin", sa.Boolean),
        sa.column("must_change_password", sa.Boolean),
    )
    # Read bootstrap email from env if available
    import os
    bootstrap_email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "admin@localhost")

    op.bulk_insert(users_table, [{
        "id": admin_id,
        "email": bootstrap_email,
        "display_name": "Super Admin",
        "password_hash": password_hash,
        "is_active": True,
        "is_platform_admin": True,
        "must_change_password": True,
    }])

    print("\n" + "=" * 60)
    print("BOOTSTRAP SUPER ADMIN CREATED")
    print(f"  Email:    {bootstrap_email}")
    print(f"  Password: {bootstrap_password}")
    print("  (you will be required to change this on first login)")
    print("=" * 60 + "\n")


def downgrade() -> None:
    op.drop_column("api_keys", "created_by_user_id")
    op.drop_column("api_keys", "profile_id")
    op.drop_table("refresh_tokens")
    op.drop_table("user_tenant_profiles")
    op.drop_table("profile_permissions")
    op.drop_table("profiles")
    op.drop_table("permissions")
    op.drop_table("users")
