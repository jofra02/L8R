from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class NotificationDeliveryItem(BaseModel):
    id: str
    event_type: str
    ticket_id: Optional[str] = None
    run_id: Optional[str] = None
    payload: Dict[str, Any]
    status: str
    attempts: int
    last_attempt_at: Optional[datetime] = None
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
