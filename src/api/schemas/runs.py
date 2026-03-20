from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime


class RunListItem(BaseModel):
    id: str
    ticket_id: str
    status: str
    decision: Optional[str] = None
    hypothesis_count: Optional[int] = None
    started_at: datetime
    ended_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RunDetail(RunListItem):
    trace_id: str
    final_answer: Optional[str] = None
    cost_json: Optional[Dict[str, Any]] = None
    state_json: Optional[Dict[str, Any]] = None


class RunTimelineEvent(BaseModel):
    id: int
    seq: int
    node: str
    created_at: datetime
    input_json: Optional[Dict[str, Any]] = None
    output_json: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}


class RunToolCall(BaseModel):
    id: str
    tool_name: str
    args_redacted: Dict[str, Any]
    result_meta: Dict[str, Any]
    status: str
    error: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RunStats(BaseModel):
    total_runs: int
    by_status: Dict[str, int]
    by_decision: Dict[str, int]
    avg_duration_seconds: Optional[float] = None
    success_rate: Optional[float] = None
