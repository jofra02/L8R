from pydantic import BaseModel, Field
from typing import Literal, Optional, List
from datetime import datetime


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    expires_at: Optional[datetime] = None
    # "tenant": key bound to the caller's tenant (default, unchanged behavior).
    # "global": platform-scoped key (customer_id='__platform__') that targets a
    # tenant per request via ?customer_id=. Platform admins only.
    scope: Literal["tenant", "global"] = "tenant"


class ApiKeyResponse(BaseModel):
    id: str
    key_prefix: str
    name: str
    is_active: bool
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime
    scope: Literal["tenant", "global"] = "tenant"

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned only on creation — includes the raw key (shown once)."""
    raw_key: str


class AuthContext(BaseModel):
    """Unified auth context for both JWT and API key authentication."""
    user_id: Optional[str] = None
    key_id: Optional[str] = None
    auth_method: str = "api_key"  # "jwt" | "api_key"
    customer_id: str
    available_tenants: List[str] = []
    role: str = ""  # deprecated, kept for backward compat
    profile_name: str = ""
    permissions: set[str] = set()
    is_platform_admin: bool = False

    def has_permission(self, perm: str) -> bool:
        return self.is_platform_admin or perm in self.permissions


# --- Auth request/response schemas ---

class LoginRequest(BaseModel):
    email: str
    password: str
    customer_id: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool = False
    user: Optional[dict] = None

class RefreshRequest(BaseModel):
    refresh_token: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class SwitchTenantRequest(BaseModel):
    customer_id: str
