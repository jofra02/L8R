from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime


class TicketSubmit(BaseModel):
    """Payload for submitting a new ticket via the API."""
    source: str = Field(default="api", description="Source identifier (e.g. 'api', 'servicenow')")
    mode: str = Field(default="incident", pattern=r"^(incident|change|validation|inquiry)$")
    severity: str = Field(default="medium", pattern=r"^(low|medium|high|critical)$")
    text: str = Field(..., min_length=1, description="Ticket description text")
    external_id: Optional[str] = None
    raw_payload: Optional[Dict[str, Any]] = None


class TicketListItem(BaseModel):
    id: str
    external_id: Optional[str] = None
    mode: str
    severity: str
    source: str
    text: str
    created_at: datetime
    updated_at: datetime
    latest_run_status: Optional[str] = None
    latest_run_decision: Optional[str] = None

    model_config = {"from_attributes": True}


class TicketDetail(TicketListItem):
    raw_payload: Optional[Dict[str, Any]] = None
    run_count: int = 0
    latest_run_id: Optional[str] = None
    latest_run_final_answer: Optional[str] = None


class TicketTimelineEvent(BaseModel):
    id: int
    run_id: str
    seq: int
    node: str
    created_at: datetime
    input_summary: Optional[Dict[str, Any]] = None
    output_summary: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}


class EvidenceItem(BaseModel):
    id: str
    tool_name: str
    content_hash: str
    storage_ref: str
    summary: str
    created_at: datetime

    model_config = {"from_attributes": True}


class HypothesisItem(BaseModel):
    id: Optional[str] = None
    title: str = ""
    description: str = ""
    confidence: Optional[float] = None
    status: Optional[str] = None
    evidence_refs: List[str] = []


class FactItem(BaseModel):
    key: str
    value: Any = None
    source_evidence_id: Optional[str] = None
    confidence: Optional[float] = None


class PlanResponse(BaseModel):
    diagnosis_steps: List[Dict[str, Any]] = []
    remediation_steps: List[Dict[str, Any]] = []
    validation_steps: List[Dict[str, Any]] = []
    rollback_steps: List[Dict[str, Any]] = []


class TicketReportResponse(BaseModel):
    ticket_id: str
    job_id: str
    status: str
    report: str
