"""add device-assessment tables and assessments permissions

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-07-18

Six tables for the Device Assessment module (definition snapshots, runs,
targets, collection executions, control results, reports) plus the
assessments:read / assessments:write permissions mapped into the three
system profiles (same pattern as c4d5e6f7a8b9).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PERMISSIONS = [
    ("assessments:read", "assessments", "read",
     "View device assessments, findings and reports"),
    ("assessments:write", "assessments", "write",
     "Create, start, cancel and re-evaluate device assessments"),
]

SUPER_ADMIN_ID = "profile_super_admin"
SUPER_ADMIN_RO_ID = "profile_super_admin_readonly"
TENANT_ADMIN_ID = "profile_tenant_admin"

ASSESSMENT_TABLES = (
    "assessment_reports",
    "assessment_control_results",
    "assessment_collection_executions",
    "assessment_targets",
    "assessment_runs",
    "assessment_definition_versions",
)


def upgrade() -> None:
    op.create_table(
        "assessment_definition_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("definition_id", sa.String(), nullable=False, index=True),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("vendor", sa.String(), nullable=False),
        sa.Column("product", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("definition_id", "version",
                            name="uq_assessment_definition_version"),
    )

    op.create_table(
        "assessment_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(),
                  sa.ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("definition_version_id", sa.String(),
                  sa.ForeignKey("assessment_definition_versions.id"),
                  nullable=False, index=True),
        sa.Column("definition_id", sa.String(), nullable=False),
        sa.Column("definition_version", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False,
                  server_default="draft", index=True),
        sa.Column("requested_by", sa.String(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("score", sa.JSON(), nullable=True),
        sa.Column("stats", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_assessment_runs_tenant_created", "assessment_runs",
                    ["customer_id", "created_at"])

    op.create_table(
        "assessment_targets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(),
                  sa.ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("run_id", sa.String(),
                  sa.ForeignKey("assessment_runs.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("component_id", sa.String(), nullable=False),
        sa.Column("device_name", sa.String(), nullable=False),
        sa.Column("device_meta", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint("run_id", "component_id",
                            name="uq_assessment_target_per_run"),
    )

    op.create_table(
        "assessment_collection_executions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(),
                  sa.ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("run_id", sa.String(),
                  sa.ForeignKey("assessment_runs.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("target_id", sa.String(),
                  sa.ForeignKey("assessment_targets.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("step_id", sa.String(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("tool_args", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw_evidence_sha", sa.String(64), nullable=True),
        sa.Column("raw_size_bytes", sa.Integer(), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("normalized", sa.JSON(), nullable=True),
        sa.Column("normalizer", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.UniqueConstraint("run_id", "target_id", "step_id",
                            name="uq_assessment_execution_step"),
    )
    op.create_index("ix_assessment_executions_run_status",
                    "assessment_collection_executions", ["run_id", "status"])

    op.create_table(
        "assessment_control_results",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(),
                  sa.ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("run_id", sa.String(),
                  sa.ForeignKey("assessment_runs.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("target_id", sa.String(),
                  sa.ForeignKey("assessment_targets.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("control_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("references", sa.JSON(), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=True),
        sa.Column("llm_output", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "target_id", "control_id",
                            name="uq_assessment_result_control"),
    )
    op.create_index("ix_assessment_results_run_status",
                    "assessment_control_results", ["run_id", "status"])
    op.create_index("ix_assessment_results_run_severity",
                    "assessment_control_results", ["run_id", "severity"])

    op.create_table(
        "assessment_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(),
                  sa.ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("run_id", sa.String(),
                  sa.ForeignKey("assessment_runs.id", ondelete="CASCADE"),
                  nullable=False, unique=True, index=True),
        sa.Column("model", sa.JSON(), nullable=False),
        sa.Column("format_version", sa.String(), nullable=False,
                  server_default="1.0"),
        sa.Column("generated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    # --- permissions seeding (pattern from c4d5e6f7a8b9) ---
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
    pp_rows.append({"profile_id": SUPER_ADMIN_RO_ID, "permission_id": "assessments:read"})
    for p in NEW_PERMISSIONS:
        pp_rows.append({"profile_id": TENANT_ADMIN_ID, "permission_id": p[0]})
    op.bulk_insert(pp_table, pp_rows)


def downgrade() -> None:
    op.execute(
        "DELETE FROM profile_permissions WHERE permission_id IN "
        "('assessments:read', 'assessments:write')"
    )
    op.execute(
        "DELETE FROM permissions WHERE id IN "
        "('assessments:read', 'assessments:write')"
    )
    for table in ASSESSMENT_TABLES:
        op.drop_table(table)
