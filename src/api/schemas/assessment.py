"""Pydantic schemas for the Device Assessment API."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --- Definitions ---

class DefinitionVersionItem(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    definition_id: str
    version: str
    vendor: str
    product: str
    name: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None


class DefinitionVersionDetail(DefinitionVersionItem):
    """Full snapshot including steps/controls for the wizard scope review."""

    step_count: int
    control_count: int
    categories: List[str]
    collection_steps: List[Dict[str, Any]]
    controls: List[Dict[str, Any]]


# --- Runs ---

class AssessmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    definition_id: str
    definition_version: str
    component_ids: List[str] = Field(min_length=1)
    params: Dict[str, Any] = Field(default_factory=dict)


class TargetResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    component_id: str
    device_name: str
    status: str
    error: Optional[str] = None


class AssessmentListItem(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    definition_id: str
    definition_version: str
    status: str
    progress: Dict[str, Any] = Field(default_factory=dict)
    score: Optional[Dict[str, Any]] = None
    stats: Optional[Dict[str, Any]] = None
    requested_by: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    device_count: int = 0


class AssessmentDetail(AssessmentListItem):
    params: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    targets: List[TargetResponse] = Field(default_factory=list)


class AssessmentCreateResponse(BaseModel):
    run: AssessmentDetail
    warnings: List[str] = Field(default_factory=list)


# --- Executions / results ---

class ExecutionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    target_id: str
    step_id: str
    tool_name: str
    status: str
    attempt: int
    error_type: Optional[str] = None
    error: Optional[str] = None
    truncated: bool = False
    raw_size_bytes: Optional[int] = None
    duration_ms: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class ControlResultResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    target_id: str
    control_id: str
    title: str
    category: str
    severity: str
    status: str
    method: str
    confidence: Optional[float] = None
    explanation: Optional[str] = None
    recommendation: Optional[str] = None
    references: Optional[List[str]] = None
    evidence_refs: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[datetime] = None


class EvidenceResponse(BaseModel):
    execution_id: str
    step_id: str
    tool_name: str
    raw: Optional[Any] = None
    normalized: Optional[Dict[str, Any]] = None
    truncated: bool = False
    raw_size_bytes: Optional[int] = None


class ReportResponse(BaseModel):
    run_id: str
    format_version: str
    generated_at: Optional[datetime] = None
    model: Dict[str, Any]
