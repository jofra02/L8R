from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, List
from datetime import datetime


# --- MCP managed connection ---

class McpConnection(BaseModel):
    """Connection details for a device managed in the MCP gateway inventory.

    The token is write-only: it is forwarded to the gateway (which encrypts
    and stores it) and is never persisted or returned by this API.
    """
    vendor: str = "fortinet"
    appliance: str = "fortigate"
    device_type: str = "fortios"
    host: str = Field(..., min_length=1)
    port: int = 443
    token: Optional[str] = None
    verify_ssl: bool = False
    primary: bool = False


class GatewaySyncStatus(BaseModel):
    """Transient result of the gateway sync performed during this request."""
    status: str  # synced | error | skipped
    reloaded: Optional[bool] = None
    error: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


# --- Component ---

class ComponentCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=256)
    ref: str = Field(..., min_length=1, max_length=256)
    role: str = Field(..., min_length=1)
    vendor: Optional[str] = None
    priority: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)
    mcp_connection: Optional[McpConnection] = None


class ComponentUpdate(BaseModel):
    ref: Optional[str] = None
    role: Optional[str] = None
    vendor: Optional[str] = None
    priority: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    mcp_connection: Optional[McpConnection] = None
    mcp_managed: Optional[bool] = None  # set False to detach the device from the gateway


class ComponentResponse(BaseModel):
    id: str
    ref: str
    role: str
    vendor: Optional[str] = None
    priority: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)
    gateway_sync: Optional[GatewaySyncStatus] = None


# --- Dependency ---

class DependencyCreate(BaseModel):
    source_id: str = Field(..., min_length=1)
    target_id: str = Field(..., min_length=1)
    relation: str = Field(..., min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DependencyResponse(BaseModel):
    source_id: str
    target_id: str
    relation: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


# --- Baseline ---

class BaselineCreate(BaseModel):
    component_id: str = Field(..., min_length=1)
    metric: str = Field(..., min_length=1)
    normal_value: str = Field(..., min_length=1)
    description: str = ""


class BaselineUpdate(BaseModel):
    normal_value: Optional[str] = None
    description: Optional[str] = None


class BaselineResponse(BaseModel):
    component_id: str
    metric: str
    normal_value: str
    description: str = ""


# --- Known Change ---

class KnownChangeCreate(BaseModel):
    date: str = Field(..., min_length=1, description="ISO date e.g. 2026-03-15")
    description: str = Field(..., min_length=1)
    component_id: Optional[str] = None
    change_type: str = "update"


class KnownChangeUpdate(BaseModel):
    date: Optional[str] = None
    description: Optional[str] = None
    component_id: Optional[str] = None
    change_type: Optional[str] = None


class KnownChangeResponse(BaseModel):
    index: int
    date: str
    description: str
    component_id: Optional[str] = None
    change_type: str = "update"


# --- Context-level ---

class InventoryOverview(BaseModel):
    customer_id: str
    version: str
    component_count: int
    dependency_count: int
    baseline_count: int
    known_change_count: int


class FullInventoryResponse(BaseModel):
    customer_id: str
    version: str
    components: List[ComponentResponse]
    dependencies: List[DependencyResponse]
    baselines: List[BaselineResponse]
    known_changes: List[KnownChangeResponse]


class InventoryImport(BaseModel):
    """Bulk import payload — replaces the entire context."""
    components: List[ComponentCreate] = Field(default_factory=list)
    dependencies: List[DependencyCreate] = Field(default_factory=list)
    baselines: List[BaselineCreate] = Field(default_factory=list)
    known_changes: List[KnownChangeCreate] = Field(default_factory=list)
