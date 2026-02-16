from sqlalchemy import String, Text, DateTime, JSON, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional, Dict, Any
from .database import Base

class TenantMixin:
    """Enforce strict isolation by customer_id on all tables."""
    customer_id: Mapped[str] = mapped_column(String, index=True, nullable=False)

class TicketORM(Base, TenantMixin):
    __tablename__ = "tickets"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    mode: Mapped[str] = mapped_column(String)  # incident|change
    severity: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    audit_logs: Mapped[list["AuditLogORM"]] = relationship(back_populates="ticket")
    evidence_refs: Mapped[list["EvidenceRefORM"]] = relationship(back_populates="ticket")

class AuditLogORM(Base, TenantMixin):
    __tablename__ = "audit_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    actor: Mapped[str] = mapped_column(String)  # user or agent/tool
    action: Mapped[str] = mapped_column(String)  # tool_call, decision, approval
    details: Mapped[Dict[str, Any]] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    ticket: Mapped["TicketORM"] = relationship(back_populates="audit_logs")

class EvidenceRefORM(Base, TenantMixin):
    __tablename__ = "evidence_refs"
    
    id: Mapped[str] = mapped_column(String, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String)
    storage_ref: Mapped[str] = mapped_column(String)  # path to blob/text store
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
