from sqlalchemy import String, Text, DateTime, Date, JSON, ForeignKey, Integer, Boolean, Float, BigInteger, Index, UniqueConstraint, Table, Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from .database import Base

# --- Mixins ---

class TenantMixin:
    """Enforce strict isolation by customer_id on all Data Plane tables."""
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

# --- Control Plane (Global / Shared) ---

class PlatformTenant(Base):
    """Platform-level tenant registry."""
    __tablename__ = "platform_tenants"

    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active")  # active, suspended
    plan: Mapped[str] = mapped_column(String, default="standard")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())  # S8

    # One-to-one relationship with endpoints. passive_deletes="all": tenant
    # deletion is handled entirely by the DB-level ON DELETE CASCADE.
    endpoints: Mapped["TenantEndpoint"] = relationship(
        back_populates="tenant", uselist=False, passive_deletes="all"
    )
    scopes: Mapped[List["CapabilityScope"]] = relationship(
        back_populates="tenant", passive_deletes="all"
    )

class TenantEndpoint(Base):
    """Infrastructure pointers for a tenant."""
    __tablename__ = "tenant_endpoints"

    customer_id: Mapped[str] = mapped_column(
        ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"), primary_key=True
    )
    pg_dsn_ref: Mapped[Optional[str]] = mapped_column(String)   # Reference to Vault/Env for connection string
    qdrant_url_ref: Mapped[Optional[str]] = mapped_column(String)
    object_store_ref: Mapped[Optional[str]] = mapped_column(String)

    tenant: Mapped["PlatformTenant"] = relationship(back_populates="endpoints")

class CapabilityScope(Base):
    """Allowed tools and quotas per tenant."""
    __tablename__ = "capability_scopes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"), index=True
    )
    scope_name: Mapped[str] = mapped_column(String)  # e.g., "network_read"
    allowed_tools: Mapped[List[str]] = mapped_column(JSON)  # e.g., ["ping", "dns*"]
    rate_limit: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped["PlatformTenant"] = relationship(back_populates="scopes")

    __table_args__ = (
        UniqueConstraint("customer_id", "scope_name", name="uq_scope_per_tenant"),  # S7
    )


# --- Data Plane (Per Tenant Logic, but possibly shared Schema if not DB-per-tenant) ---
# Note: In a shared DB model, these use TenantMixin. In DB-per-tenant, usage varies,
# but for the ORM definition we keep TenantMixin to support both safely.

class TicketORM(Base, TenantMixin):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    external_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    mode: Mapped[str] = mapped_column(String)  # incident|change
    severity: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    agent_runs: Mapped[List["AgentRunORM"]] = relationship(back_populates="ticket")
    audit_logs: Mapped[list["AuditLogORM"]] = relationship(back_populates="ticket")
    evidence_refs: Mapped[list["EvidenceRefORM"]] = relationship(back_populates="ticket")

    __table_args__ = (
        Index("ix_tickets_tenant_created", "customer_id", "created_at"),  # S3
    )

class AgentRunORM(Base, TenantMixin):
    """Tracks a specific execution session for a ticket."""
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)  # S4
    trace_id: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String)  # running, completed, failed
    state_json: Mapped[Dict[str, Any]] = mapped_column(JSON)  # Snapshot of GlobalState
    cost_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # S6: Denormalized summary columns to avoid loading full state_json for list views
    final_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hypothesis_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # proceed_to_plan | escalate_to_human

    ticket: Mapped["TicketORM"] = relationship(back_populates="agent_runs")
    events: Mapped[List["AgentEventORM"]] = relationship(back_populates="run")
    tool_calls: Mapped[List["ToolCallAuditORM"]] = relationship(back_populates="run")

    __table_args__ = (
        Index("ix_agent_runs_tenant_ticket", "customer_id", "ticket_id"),  # S3
    )

class AgentEventORM(Base, TenantMixin):
    """Granular steps/nodes visited in LangGraph."""
    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)  # S4
    seq: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String)
    input_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    output_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["AgentRunORM"] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_agent_events_run_seq", "run_id", "seq"),  # S3
    )

class ToolCallAuditORM(Base, TenantMixin):
    """Detailed audit of every MCP tool execution."""
    __tablename__ = "tool_calls_audit"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)  # S4
    tool_name: Mapped[str] = mapped_column(String)
    args_redacted: Mapped[Dict[str, Any]] = mapped_column(JSON)
    result_meta: Mapped[Dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped["AgentRunORM"] = relationship(back_populates="tool_calls")

    __table_args__ = (
        Index("ix_tool_calls_run_status", "run_id", "status"),  # S3
    )

class AuditLogORM(Base, TenantMixin):
    """Legacy simple audit - kept for compatibility or high level events."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)  # S4
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped["TicketORM"] = relationship(back_populates="audit_logs")

class EvidenceRefORM(Base, TenantMixin):
    """Refs to blobs in Object Store."""
    __tablename__ = "evidence_refs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)  # S4
    tool_name: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String)
    storage_ref: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped["TicketORM"] = relationship(back_populates="evidence_refs")

class ClientContextORM(Base, TenantMixin):
    """Long-term context for a customer."""
    __tablename__ = "client_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String)  # e.g., "v1.0"
    content: Mapped[Dict[str, Any]] = mapped_column(JSON)  # Stores the full ClientContext model
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_client_contexts_tenant_active", "customer_id", "is_active"),  # S3
        # S2: Partial unique index — only one active context allowed per tenant.
        # postgresql_where makes this a PostgreSQL partial index.
        Index(
            "uq_client_context_active",
            "customer_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

class ApiKeyORM(Base):
    """API keys for authentication. Platform keys use customer_id='__platform__'."""
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"), index=True, nullable=False,
    )
    key_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # deprecated — kept for backward compat
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_api_keys_customer_active", "customer_id", "is_active"),
    )


# --- RBAC (Control Plane) ---

class UserORM(Base):
    """Employee user accounts (control plane, no TenantMixin)."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tenant_profiles: Mapped[List["UserTenantProfileORM"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    refresh_tokens: Mapped[List["RefreshTokenORM"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class PermissionORM(Base):
    """Granular permission catalog (seeded via migration)."""
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. "tickets:read"
    resource: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "tickets"
    action: Mapped[str] = mapped_column(String, nullable=False)    # e.g. "read"
    description: Mapped[str] = mapped_column(String, nullable=False)


# Junction table: profile <-> permission (many-to-many)
profile_permissions = Table(
    "profile_permissions",
    Base.metadata,
    Column("profile_id", String, ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", String, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class ProfileORM(Base):
    """Named permission sets (roles)."""
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    permissions: Mapped[List["PermissionORM"]] = relationship(secondary=profile_permissions, lazy="selectin")


class UserTenantProfileORM(Base):
    """Junction: user x tenant x profile. One profile per tenant per user."""
    __tablename__ = "user_tenant_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("platform_tenants.customer_id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["UserORM"] = relationship(back_populates="tenant_profiles")
    tenant: Mapped["PlatformTenant"] = relationship()
    profile: Mapped["ProfileORM"] = relationship()

    __table_args__ = (
        UniqueConstraint("user_id", "customer_id", name="uq_user_tenant_profile"),
        Index("ix_user_tenant_profiles_customer", "customer_id"),
    )


class RefreshTokenORM(Base):
    """JWT refresh tokens."""
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["UserORM"] = relationship(back_populates="refresh_tokens")


class CheckpointORM(Base, TenantMixin):
    """Persistence for LangGraph state."""
    __tablename__ = "checkpoints"

    thread_id: Mapped[str] = mapped_column(String, primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String, primary_key=True)
    parent_checkpoint_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    checkpoint: Mapped[Dict[str, Any]] = mapped_column(JSON)  # Serialization of global state
    metadata_: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Device Assessment module ---

class AssessmentDefinitionVersionORM(Base):
    """Immutable snapshot of an assessment definition version.

    Authored as YAML in src/assessments/definitions/ and synced here by the
    DefinitionRegistry. content holds the full parsed definition (collection
    steps, controls, scoring); content_hash guards immutability — a changed
    file with the same version is rejected at sync time.
    """
    __tablename__ = "assessment_definition_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    definition_id: Mapped[str] = mapped_column(String, index=True)  # e.g. fortigate-security-baseline
    version: Mapped[str] = mapped_column(String)                    # semver
    vendor: Mapped[str] = mapped_column(String)
    product: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("definition_id", "version", name="uq_assessment_definition_version"),
    )


class AssessmentRunORM(Base, TenantMixin):
    """One assessment execution over a set of devices, pinned to a definition version."""
    __tablename__ = "assessment_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    definition_version_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_definition_versions.id"), index=True
    )
    # Denormalized for list views without joining the definition snapshot
    definition_id: Mapped[str] = mapped_column(String)
    definition_version: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    # draft|queued|collecting|evaluating|completed|completed_with_errors|failed|cancelled
    status: Mapped[str] = mapped_column(String, index=True, default="draft")
    requested_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # user_id
    params: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    progress: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    score: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    stats: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)  # findings by severity
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    targets: Mapped[List["AssessmentTargetORM"]] = relationship(
        back_populates="run", passive_deletes="all"
    )

    __table_args__ = (
        Index("ix_assessment_runs_tenant_created", "customer_id", "created_at"),
    )


class AssessmentTargetORM(Base, TenantMixin):
    """A device evaluated within an assessment run (inventory snapshot at creation)."""
    __tablename__ = "assessment_targets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="CASCADE"), index=True
    )
    component_id: Mapped[str] = mapped_column(String)
    device_name: Mapped[str] = mapped_column(String)   # display label (routing uses component_id)
    device_meta: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # pending|collecting|collected|partial|failed|skipped
    status: Mapped[str] = mapped_column(String, default="pending")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped["AssessmentRunORM"] = relationship(back_populates="targets")

    __table_args__ = (
        UniqueConstraint("run_id", "component_id", name="uq_assessment_target_per_run"),
    )


class AssessmentCollectionExecutionORM(Base, TenantMixin):
    """Forensic record of one collection step execution on one target.

    This is the assessment counterpart of tool_calls_audit (whose run_id FK
    points to agent_runs and therefore cannot host assessment calls). Also
    carries the evidence references (raw blob sha + normalized JSON).
    """
    __tablename__ = "assessment_collection_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_targets.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[str] = mapped_column(String)
    tool_name: Mapped[str] = mapped_column(String)
    tool_args: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)  # sanitized
    # pending|running|success|failed|timeout|skipped|cancelled
    status: Mapped[str] = mapped_column(String, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    # connection|timeout|authorization|schema|device|unknown
    error_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_evidence_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    raw_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    normalized: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    normalizer: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "target_id", "step_id", name="uq_assessment_execution_step"),
        Index("ix_assessment_executions_run_status", "run_id", "status"),
    )


class AssessmentControlResultORM(Base, TenantMixin):
    """Evaluation outcome of one control on one target (a fail/warning is a finding)."""
    __tablename__ = "assessment_control_results"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_targets.id", ondelete="CASCADE"), index=True
    )
    control_id: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)  # critical|high|medium|low
    # pass|fail|warning|not_applicable|not_evaluated|insufficient_evidence|error
    status: Mapped[str] = mapped_column(String)
    method: Mapped[str] = mapped_column(String)    # rule|parser|llm|hybrid
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    references: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    evidence_refs: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    llm_output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("run_id", "target_id", "control_id", name="uq_assessment_result_control"),
        Index("ix_assessment_results_run_status", "run_id", "status"),
        Index("ix_assessment_results_run_severity", "run_id", "severity"),
    )


class AssessmentReportORM(Base, TenantMixin):
    """View-independent report model for a completed assessment run."""
    __tablename__ = "assessment_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    model: Mapped[Dict[str, Any]] = mapped_column(JSON)
    format_version: Mapped[str] = mapped_column(String, default="1.0")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Outbound notifications ---

class NotificationDeliveryORM(Base, TenantMixin):
    """One outbound notification delivery (payload snapshot + attempt result).

    payload is the exact JSON sent to the external endpoint; a manual resend
    re-sends this snapshot unchanged. ticket_id/run_id are nullable so future
    event types without an associated ticket or run fit the same table.
    """
    __tablename__ = "notification_deliveries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, index=True)  # ticket.ingested | run.completed
    ticket_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True, nullable=True
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True, nullable=True
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)  # pending|delivered|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # truncated to 4000 chars
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_notification_deliveries_tenant_created", "customer_id", "created_at"),
    )


# --- Asset Inventory module ---
#
# Deliberate deviation from the sa.JSON convention: asset tables use
# postgresql.JSONB + GIN indexes because the search surface (dynamic
# attributes, tags) requires containment operators. The codebase is
# Postgres-only (asyncpg DSN, partial indexes, pg_insert in evidence_store).
# The sqlite variant exists ONLY so the self-contained test suite can run
# against in-memory sqlite; production DDL (alembic) is pure JSONB.

PortableJSONB = JSONB().with_variant(JSON(), "sqlite")

class AssetORM(Base, TenantMixin):
    """One inventory asset. Relational successor of the Component entries
    formerly embedded in client_contexts.content (see context_adapter)."""
    __tablename__ = "assets"

    # updated_at is server-generated (onupdate=func.now()); without eager
    # fetch SQLAlchemy expires it after an UPDATE flush and the next attribute
    # access lazy-loads synchronously — MissingGreenlet under the async
    # session when the router serializes the returned instance.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    ref: Mapped[str] = mapped_column(String, nullable=False)  # human reference slug (search/import; routing uses id)
    asset_type: Mapped[str] = mapped_column(String, nullable=False)
    type_schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    manufacturer: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Commercial product name ("FortiGate", "ESXi"), complementary to model.
    # Values are constrained to the global asset_products catalog; manual-only
    # (deliberately absent from MAPPABLE_COMMON_TARGETS).
    product_name: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    serial_number: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    location: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    owner: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    fqdn: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)  # active|inactive|maintenance|retired
    criticality: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # low|medium|high|critical
    tags: Mapped[List[str]] = mapped_column(PortableJSONB, default=list, nullable=False)
    purchase_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    warranty_expires: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    eol_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Type-specific attributes, schema-validated against the asset-type
    # definition. provenance maps attribute/field name -> origin descriptor
    # ({source: manual|discovered, pack_id, run_id, updated_at}).
    attributes: Mapped[Dict[str, Any]] = mapped_column(PortableJSONB, default=dict, nullable=False)
    provenance: Mapped[Dict[str, Any]] = mapped_column(PortableJSONB, default=dict, nullable=False)

    # MCP gateway management. mcp_config never holds the token (write-only
    # to the gateway, Fernet-encrypted at rest gateway-side).
    managed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mcp_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(PortableJSONB, nullable=True)
    sync_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # pending|synced|error|skipped
    sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    external_source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_assets_tenant_created", "customer_id", "created_at"),
        Index("ix_assets_tenant_type", "customer_id", "asset_type"),
        Index("ix_assets_tenant_status", "customer_id", "status"),
        Index("ix_assets_attributes_gin", "attributes", postgresql_using="gin",
              postgresql_ops={"attributes": "jsonb_path_ops"}),
        Index("ix_assets_tags_gin", "tags", postgresql_using="gin"),
        Index("uq_assets_tenant_ref", "customer_id", "ref", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        Index("uq_assets_external_identity", "customer_id", "external_source", "external_id",
              unique=True,
              postgresql_where=text("external_id IS NOT NULL AND deleted_at IS NULL")),
    )


class AssetRelationORM(Base, TenantMixin):
    """Directed relation between two assets (successor of blob dependencies)."""
    __tablename__ = "asset_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    target_asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String, nullable=False)  # depends_on|managed_by|connected_to|member_of|...
    provenance: Mapped[str] = mapped_column(String, default="manual", nullable=False)  # manual|discovered
    details: Mapped[Dict[str, Any]] = mapped_column(PortableJSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("customer_id", "source_asset_id", "target_asset_id", "relation_type",
                         name="uq_asset_relation"),
    )


class AssetDefinitionVersionORM(Base):
    """Immutable snapshot of an asset-type or enrichment-pack definition.

    Same immutability contract as AssessmentDefinitionVersionORM: YAML in
    src/assets/definitions/ is the authoring source; same (kind,
    definition_id, version) with different content_hash is rejected at sync.
    Global catalog — no TenantMixin.
    """
    __tablename__ = "asset_definition_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # asset_type | enrichment_pack
    definition_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[Dict[str, Any]] = mapped_column(PortableJSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("kind", "definition_id", "version", name="uq_asset_definition_version"),
    )


class AssetProductORM(Base):
    """Global product catalog entry ("FortiGate", "ESXi", ...).

    Reference data, not tenant data — no TenantMixin (same stance as
    AssetDefinitionVersionORM). Assets store the product name denormalized
    (assets.product_name, no FK); this table is the source of truth for
    allowed values. Renames propagate via bulk UPDATE; deletes are blocked
    while any non-deleted asset references the name.
    """
    __tablename__ = "asset_products"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("uq_asset_products_name_lower", text("lower(name)"), unique=True),
    )


class AssetSyncRunORM(Base, TenantMixin):
    """One enrichment/discovery execution against one managed asset."""
    __tablename__ = "asset_sync_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    pack_id: Mapped[str] = mapped_column(String, nullable=False)
    pack_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # pending|running|completed|completed_with_errors|failed
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    trigger: Mapped[str] = mapped_column(String, nullable=False)  # auto|manual|scheduled|import
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stats: Mapped[Dict[str, Any]] = mapped_column(PortableJSONB, default=dict, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_asset_sync_runs_tenant_asset_created", "customer_id", "asset_id", "created_at"),
    )


class AssetSubitemORM(Base, TenantMixin):
    """Discovered sub-entity of an asset (e.g. an EDR collector endpoint).

    Deliberately NOT an asset: assets are curated (human/import created,
    ref-unique, type-schema validated, lifecycle-managed); subitems are
    source-owned observations attached to a parent asset for visibility.
    Enrichment upserts them by (customer_id, parent, source, kind,
    external_id) and marks rows absent when a complete scan no longer
    returns them — never deletes. Promotion to a real asset is a future
    explicit curation action (promoted_asset_id reserves the link).
    """
    __tablename__ = "asset_subitems"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    parent_asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Self-reference for discovered hierarchies (endpoint -> interface, ...).
    # NULL = root-level subitem directly under the asset.
    parent_subitem_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asset_subitems.id", ondelete="CASCADE"), nullable=True
    )
    source: Mapped[str] = mapped_column(String, nullable=False)  # e.g. fortiedr
    kind: Mapped[str] = mapped_column(String, nullable=False)    # e.g. endpoint
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Normalized status as reported by the source (first-class for aggregates)
    state: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    attributes: Mapped[Dict[str, Any]] = mapped_column(PortableJSONB, default=dict, nullable=False)
    # True when the last complete scan of the source no longer returned it
    absent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asset_sync_runs.id", ondelete="SET NULL"), nullable=True
    )
    promoted_asset_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Identity is scoped to the hierarchy level: roots dedupe under the
        # asset, children under their parent subitem — two children of
        # different parents may legitimately share (source, kind,
        # external_id) (e.g. interface port1 on two vdoms). A single unique
        # constraint including the nullable column would stop deduping
        # roots on Postgres (NULLs compare distinct).
        Index(
            "uq_asset_subitem_identity_root",
            "customer_id", "parent_asset_id", "source", "kind", "external_id",
            unique=True,
            postgresql_where=text("parent_subitem_id IS NULL"),
            sqlite_where=text("parent_subitem_id IS NULL"),
        ),
        Index(
            "uq_asset_subitem_identity_child",
            "customer_id", "parent_subitem_id", "source", "kind", "external_id",
            unique=True,
            postgresql_where=text("parent_subitem_id IS NOT NULL"),
            sqlite_where=text("parent_subitem_id IS NOT NULL"),
        ),
        Index("ix_asset_subitems_tenant_parent", "customer_id", "parent_asset_id"),
        Index("ix_asset_subitems_parent_subitem", "customer_id", "parent_subitem_id"),
    )


class AssetAuditLogORM(Base, TenantMixin):
    """Per-asset change audit (who/what/when + field-level diff).

    AuditLogORM is unusable here (NOT NULL FK to tickets); this mirrors the
    NotificationDeliveryORM precedent of module-owned nullable refs.
    """
    __tablename__ = "asset_audit_log"

    # BigInteger in production; sqlite needs INTEGER for autoincrement (tests)
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    actor: Mapped[str] = mapped_column(String, nullable=False)  # user email | system:enrichment | api_key:<id>
    # created|updated|deleted|restored|imported|enriched|relation_added|relation_removed|sync_status_changed
    action: Mapped[str] = mapped_column(String, nullable=False)
    changes: Mapped[Dict[str, Any]] = mapped_column(PortableJSONB, default=dict, nullable=False)  # {field: {old, new}}
    sync_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("asset_sync_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_asset_audit_tenant_asset_created", "customer_id", "asset_id", "created_at"),
    )
