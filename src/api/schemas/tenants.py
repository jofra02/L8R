from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# --- Request schemas ---

class TenantCreate(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=256)
    plan: str = Field(default="standard", max_length=64)


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=256)
    plan: Optional[str] = Field(None, max_length=64)


class EndpointUpsert(BaseModel):
    pg_dsn_ref: Optional[str] = None
    qdrant_url_ref: Optional[str] = None
    object_store_ref: Optional[str] = None


class ScopeCreate(BaseModel):
    scope_name: str = Field(..., min_length=1, max_length=128)
    allowed_tools: List[str] = Field(default_factory=list)
    rate_limit: Optional[int] = Field(None, ge=1)


class ScopeUpdate(BaseModel):
    scope_name: Optional[str] = Field(None, min_length=1, max_length=128)
    allowed_tools: Optional[List[str]] = None
    rate_limit: Optional[int] = Field(None, ge=0)


# --- Response schemas ---

class TenantListItem(BaseModel):
    customer_id: str
    name: str
    status: str
    plan: str
    user_count: int = 0
    ticket_count: int = 0
    last_activity: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TenantCreateResponse(TenantListItem):
    # Outcome of the best-effort MCP gateway inventory provisioning
    # (GatewaySyncResult: status synced|error|skipped, reloaded, error, warnings)
    gateway_sync: Optional[dict] = None


class EndpointResponse(BaseModel):
    customer_id: str
    pg_dsn_ref: Optional[str] = None
    qdrant_url_ref: Optional[str] = None
    object_store_ref: Optional[str] = None

    model_config = {"from_attributes": True}


class ScopeResponse(BaseModel):
    id: int
    customer_id: str
    scope_name: str
    allowed_tools: List[str]
    rate_limit: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TenantDetail(BaseModel):
    customer_id: str
    name: str
    status: str
    plan: str
    created_at: datetime
    updated_at: datetime
    user_count: int = 0
    ticket_count: int = 0
    last_activity: Optional[datetime] = None
    endpoints: Optional[EndpointResponse] = None
    scopes: List[ScopeResponse] = []


class CascadeWarning(BaseModel):
    user_count: int
    ticket_count: int
    api_key_count: int
    message: str
