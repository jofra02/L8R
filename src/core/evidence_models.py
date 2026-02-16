from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime

class BaseEvidence(BaseModel):
    """Base class for all normalized evidence."""
    timestamp: datetime = Field(default_factory=datetime.now)
    observer: str = Field(description="Tool or agent that observed this")
    raw_data: Optional[Dict[str, Any]] = None

class NetworkTraffic(BaseEvidence):
    """Normalized network traffic event (ECS-like)."""
    source_ip: Optional[str] = None
    source_port: Optional[int] = None
    destination_ip: Optional[str] = None
    destination_port: Optional[int] = None
    protocol: str = "tcp"
    action: str = "allow" # allow, deny, drop
    bytes_sent: Optional[int] = None
    bytes_received: Optional[int] = None

class ProcessEvent(BaseEvidence):
    """Normalized process execution event."""
    pid: int
    parent_pid: Optional[int] = None
    command_line: str
    user: str
    executable_path: str
    hash: Optional[str] = None

class SystemResource(BaseEvidence):
    """System resource usage snapshot."""
    hostname: str
    cpu_usage_percent: float
    memory_usage_percent: float
    disk_usage_percent: float
    uptime_seconds: int

class ServiceStatus(BaseEvidence):
    """Status of a specific service."""
    service_name: str
    status: str # running, stopped, failed
    start_type: str # auto, manual
    
# Registry of supported types for serialization
EVIDENCE_TYPES = {
    "network": NetworkTraffic,
    "process": ProcessEvent,
    "resource": SystemResource,
    "service": ServiceStatus
}
