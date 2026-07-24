from sqlalchemy import String, Text, DateTime, JSON, ForeignKey, Integer, Boolean, Float, BigInteger, Index, UniqueConstraint, Table, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text
from datetime import datetime
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
    device_name: Mapped[str] = mapped_column(String)   # gateway routing ref
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
