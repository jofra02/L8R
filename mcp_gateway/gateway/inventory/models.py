"""Inventory models — vendor-agnostic definitions for tenants and devices."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Device(BaseModel):
    """A generic infrastructure device (firewall, switch, server, ...)."""

    id: str = Field(..., description="Unique identifier for the device (slug)")
    name: str = Field(..., description="Human readable name")
    type: str = Field(..., description="Device driver type (e.g. 'fortios', 'cisco_ios', 'linux')")
    os_version: Optional[str] = Field(
        default=None, description="Firmware/OS version of the device (e.g. '7.4.5')"
    )
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    primary: bool = Field(
        default=False,
        description="Marks the default target when a tool call carries no 'device' header",
    )

    # Generic connection details; the vendor's auth strategy and routing client
    # decide how to interpret them (host, port, token, verify_ssl, ...).
    connection: Dict[str, Any] = Field(default_factory=dict)


class TenantContext(BaseModel):
    """Environment context (criticality, contacts, compliance)."""

    critical_networks: List[Dict[str, str]] = Field(
        default_factory=list, description="Critical CIDRs and their descriptions"
    )
    contacts: List[Dict[str, str]] = Field(default_factory=list, description="Key contacts")
    compliance: List[str] = Field(default_factory=list, description="Compliance frameworks (PCI, HIPAA, ...)")
    extra: Dict[str, Any] = Field(default_factory=dict)


class Tenant(BaseModel):
    """A client/environment. Its id matches a support_ai_agent customer_id."""

    id: str = Field(..., description="Unique identifier for the tenant (customer_id)")
    name: str = Field(..., description="Display name of the client")
    description: Optional[str] = None

    context: TenantContext = Field(default_factory=TenantContext)
