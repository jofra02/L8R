"""nested subitems: parent_subitem_id self-reference

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-07-30

Discovered hierarchies (endpoint -> interface, vdom -> interface, ...):
asset_subitems gains a nullable self-referencing parent_subitem_id
(CASCADE). Identity dedup becomes level-scoped via two partial unique
indexes — a single composite unique including the nullable column would
stop deduping root rows on Postgres (NULLs compare distinct), and children
of different parents may legitimately share (source, kind, external_id).

No data backfill: every existing row is a root (NULL is correct).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "asset_subitems",
        sa.Column("parent_subitem_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_asset_subitems_parent_subitem",
        "asset_subitems", "asset_subitems",
        ["parent_subitem_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_asset_subitems_parent_subitem",
        "asset_subitems",
        ["customer_id", "parent_subitem_id"],
    )
    op.drop_constraint("uq_asset_subitem_identity", "asset_subitems", type_="unique")
    op.create_index(
        "uq_asset_subitem_identity_root",
        "asset_subitems",
        ["customer_id", "parent_asset_id", "source", "kind", "external_id"],
        unique=True,
        postgresql_where=sa.text("parent_subitem_id IS NULL"),
    )
    op.create_index(
        "uq_asset_subitem_identity_child",
        "asset_subitems",
        ["customer_id", "parent_subitem_id", "source", "kind", "external_id"],
        unique=True,
        postgresql_where=sa.text("parent_subitem_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_asset_subitem_identity_child", table_name="asset_subitems")
    op.drop_index("uq_asset_subitem_identity_root", table_name="asset_subitems")
    # Nested rows cannot exist under the old schema; drop them before the
    # column so the unique constraint can be restored safely.
    op.execute("DELETE FROM asset_subitems WHERE parent_subitem_id IS NOT NULL")
    op.drop_index("ix_asset_subitems_parent_subitem", table_name="asset_subitems")
    op.drop_constraint("fk_asset_subitems_parent_subitem", "asset_subitems", type_="foreignkey")
    op.drop_column("asset_subitems", "parent_subitem_id")
    op.create_unique_constraint(
        "uq_asset_subitem_identity",
        "asset_subitems",
        ["customer_id", "parent_asset_id", "source", "kind", "external_id"],
    )
