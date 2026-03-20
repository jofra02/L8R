from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class AuditLogResponse(BaseModel):
    id: int
    ticket_id: str
    actor: str
    action: str
    details: Dict[str, Any]
    timestamp: datetime

    model_config = {"from_attributes": True}


class ToolCallResponse(BaseModel):
    id: str
    run_id: str
    tool_name: str
    args_redacted: Dict[str, Any]
    result_meta: Dict[str, Any]
    status: str
    error: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
