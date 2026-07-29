from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from src.api.schemas.inventory import GatewaySyncStatus, McpConnection

AssetStatus = Literal["active", "inactive", "maintenance", "retired"]
Criticality = Literal["low", "medium", "high", "critical"]


# --- Assets ---

class AssetCreate(BaseModel):
    id: Optional[str] = Field(default=None, max_length=256,
                              description="Optional stable id (imports/compat); server generates a uuid otherwise")
    name: str = Field(..., min_length=1, max_length=256)
    ref: Optional[str] = Field(default=None, max_length=256,
                               description="MCP device routing slug; defaults to name")
    asset_type: str = Field(..., min_length=1)
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = None
    owner: Optional[str] = None
    ip_address: Optional[str] = None
    fqdn: Optional[str] = None
    status: AssetStatus = "active"
    criticality: Optional[Criticality] = None
    tags: List[str] = Field(default_factory=list)
    purchase_date: Optional[date] = None
    warranty_expires: Optional[date] = None
    eol_date: Optional[date] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    mcp_connection: Optional[McpConnection] = None


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    ref: Optional[str] = None
    asset_type: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = None
    owner: Optional[str] = None
    ip_address: Optional[str] = None
    fqdn: Optional[str] = None
    status: Optional[AssetStatus] = None
    criticality: Optional[Criticality] = None
    tags: Optional[List[str]] = None
    purchase_date: Optional[date] = None
    warranty_expires: Optional[date] = None
    eol_date: Optional[date] = None
    attributes: Optional[Dict[str, Any]] = None
    mcp_connection: Optional[McpConnection] = None
    mcp_managed: Optional[bool] = None  # set False to detach from the gateway


class AssetResponse(BaseModel):
    id: str
    customer_id: str
    name: str
    ref: str
    asset_type: str
    type_schema_version: int
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = None
    owner: Optional[str] = None
    ip_address: Optional[str] = None
    fqdn: Optional[str] = None
    status: str
    criticality: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    purchase_date: Optional[date] = None
    warranty_expires: Optional[date] = None
    eol_date: Optional[date] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    managed: bool = False
    mcp_config: Optional[Dict[str, Any]] = None
    sync_status: Optional[str] = None
    sync_error: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    external_source: Optional[str] = None
    external_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    gateway_sync: Optional[GatewaySyncStatus] = None  # transient, mutation responses only


# --- Relations ---

class RelationCreate(BaseModel):
    target_asset_id: str = Field(..., min_length=1)
    relation_type: str = Field(..., min_length=1)
    direction: Literal["out", "in"] = "out"  # out: path asset is source
    details: Dict[str, Any] = Field(default_factory=dict)


class RelationResponse(BaseModel):
    id: int
    source_asset_id: str
    target_asset_id: str
    relation_type: str
    provenance: str
    details: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    source_name: Optional[str] = None
    target_name: Optional[str] = None


# --- History / sync runs ---

class AssetAuditEntry(BaseModel):
    id: int
    asset_id: str
    actor: str
    action: str
    changes: Dict[str, Any] = Field(default_factory=dict)
    sync_run_id: Optional[str] = None
    created_at: datetime


class SyncRunResponse(BaseModel):
    id: str
    asset_id: str
    pack_id: str
    pack_version: int
    status: str
    trigger: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    stats: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    created_at: datetime


# --- Import ---

class ImportRowResult(BaseModel):
    row: int
    action: Literal["create", "update", "skip", "error"]
    asset_id: Optional[str] = None
    errors: List[str] = Field(default_factory=list)


class ImportResponse(BaseModel):
    dry_run: bool
    total: int
    created: int
    updated: int
    skipped: int
    failed: int
    rows: List[ImportRowResult]


class AssetImportPayload(BaseModel):
    assets: List[Dict[str, Any]] = Field(default_factory=list)
