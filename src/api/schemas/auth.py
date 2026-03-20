from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    role: str = Field(default="operator", pattern=r"^(platform_admin|tenant_admin|operator|viewer)$")
    expires_at: Optional[datetime] = None


class ApiKeyResponse(BaseModel):
    id: str
    key_prefix: str
    name: str
    role: str
    is_active: bool
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned only on creation — includes the raw key (shown once)."""
    raw_key: str


class AuthContext(BaseModel):
    customer_id: str
    role: str
    key_id: str
