from sqlalchemy import String, Text, DateTime, JSON, ForeignKey, Integer, Boolean, Float, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional, Dict, Any, List
from .database import Base

# --- Mixins ---

class TenantMixin:
    """Enforce strict isolation by customer_id on all Data Plane tables."""
    customer_id: Mapped[str] = mapped_column(String, index=True, nullable=False)

# --- Control Plane (Global / Shared) ---

class PlatformTenant(Base):
    """Platform-level tenant registry."""
    __tablename__ = "platform_tenants"

    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active")  # active, suspended
    plan: Mapped[str] = mapped_column(String, default="standard")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    # One-to-one relationship with endpoints
    endpoints: Mapped["TenantEndpoint"] = relationship(back_populates="tenant", uselist=False)
    scopes: Mapped[List["CapabilityScope"]] = relationship(back_populates="tenant")

class TenantEndpoint(Base):
    """Infrastructure pointers for a tenant."""
    __tablename__ = "tenant_endpoints"

    customer_id: Mapped[str] = mapped_column(ForeignKey("platform_tenants.customer_id"), primary_key=True)
    pg_dsn_ref: Mapped[Optional[str]] = mapped_column(String)   # Reference to Vault/Env for connection string
    qdrant_url_ref: Mapped[Optional[str]] = mapped_column(String)
    object_store_ref: Mapped[Optional[str]] = mapped_column(String)
    
    tenant: Mapped["PlatformTenant"] = relationship(back_populates="endpoints")

class CapabilityScope(Base):
    """Allowed tools and quotas per tenant."""
    __tablename__ = "capability_scopes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("platform_tenants.customer_id"), index=True)
    scope_name: Mapped[str] = mapped_column(String) # e.g., "network_read"
    allowed_tools: Mapped[List[str]] = mapped_column(JSON) # e.g., ["ping", "dns*"]
    rate_limit: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped["PlatformTenant"] = relationship(back_populates="scopes")


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    agent_runs: Mapped[List["AgentRunORM"]] = relationship(back_populates="ticket")
    audit_logs: Mapped[list["AuditLogORM"]] = relationship(back_populates="ticket") # Legacy simple audit
    evidence_refs: Mapped[list["EvidenceRefORM"]] = relationship(back_populates="ticket") # Legacy Ref

class AgentRunORM(Base, TenantMixin):
    """Tracks a specific execution session for a ticket."""
    __tablename__ = "agent_runs"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    trace_id: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String) # running, completed, failed
    state_json: Mapped[Dict[str, Any]] = mapped_column(JSON) # Snapshot of GlobalState
    cost_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    ticket: Mapped["TicketORM"] = relationship(back_populates="agent_runs")
    events: Mapped[List["AgentEventORM"]] = relationship(back_populates="run")
    tool_calls: Mapped[List["ToolCallAuditORM"]] = relationship(back_populates="run")

class AgentEventORM(Base, TenantMixin):
    """Granular steps/nodes visited in LangGraph."""
    __tablename__ = "agent_events"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String)
    input_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    output_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    run: Mapped["AgentRunORM"] = relationship(back_populates="events")

class ToolCallAuditORM(Base, TenantMixin):
    """Detailed audit of every MCP tool execution."""
    __tablename__ = "tool_calls_audit"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String)
    args_redacted: Mapped[Dict[str, Any]] = mapped_column(JSON)
    result_meta: Mapped[Dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    run: Mapped["AgentRunORM"] = relationship(back_populates="tool_calls")

class AuditLogORM(Base, TenantMixin):
    """Legacy simple audit - kept for compatibility or high level events."""
    __tablename__ = "audit_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    ticket: Mapped["TicketORM"] = relationship(back_populates="audit_logs")

class EvidenceRefORM(Base, TenantMixin):
    """Refs to blobs in Object Store."""
    __tablename__ = "evidence_refs"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
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

class CheckpointORM(Base, TenantMixin):
    """Persistence for LangGraph state."""
    __tablename__ = "checkpoints"
    
    thread_id: Mapped[str] = mapped_column(String, primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String, primary_key=True)
    parent_checkpoint_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    checkpoint: Mapped[Dict[str, Any]] = mapped_column(JSON)  # Serialization of global state
    metadata_: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
