"""
Type-aware argument sanitizer for MCP tool execution.

Centralizes the logic for mapping component identifiers to tool argument keys
based on semantic type (executor vs target roles). Replaces inline injection
blocks in evidence_collector.py and investigator.py.

Also provides a pluggable value derivation system: derivation rules compute
tool-ready metadata from raw component identifiers (e.g., CIDR -> probe IP).
"""

import ipaddress
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.models import Component

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role classification
# ---------------------------------------------------------------------------

EXECUTOR_ROLES = frozenset([
    "firewall", "router", "switch", "server", "host", "loadbalancer",
    "appliance", "controller", "gateway", "hypervisor", "node", "cluster",
    "database", "storage", "nas", "san",
])

TARGET_ROLES = frozenset([
    "subnet", "network", "ip", "address", "url", "service", "process",
    "endpoint", "user", "application", "container", "pod", "vm", "instance",
])

# ---------------------------------------------------------------------------
# Argument key classification
# ---------------------------------------------------------------------------

EXECUTOR_ARG_KEYS = frozenset([
    "device", "host", "hostname", "node", "server", "appliance",
])

TARGET_ARG_KEYS = frozenset([
    "target", "ip", "address", "subnet", "destination", "network", "cidr",
])

# ---------------------------------------------------------------------------
# Placeholder detection
# ---------------------------------------------------------------------------

PLACEHOLDER_VALUES = frozenset([
    "", "<device>", "DEVICE", "<target>", "TARGET",
    "<host>", "HOST", "<hostname>", "HOSTNAME",
    "<ip>", "IP", "<address>", "ADDRESS",
    "<subnet>", "SUBNET", "<network>", "NETWORK",
    "<destination>", "DESTINATION", "<node>", "NODE",
    "<server>", "SERVER", "<cidr>", "CIDR",
])

# ---------------------------------------------------------------------------
# Role helpers
# ---------------------------------------------------------------------------


def is_executor_role(role: str) -> bool:
    """Return True if *role* (case-insensitive) matches an executor pattern."""
    role_lower = role.lower()
    return any(r in role_lower for r in EXECUTOR_ROLES)


def is_target_role(role: str) -> bool:
    """Return True if *role* (case-insensitive) matches a target pattern."""
    role_lower = role.lower()
    return any(r in role_lower for r in TARGET_ROLES)


# ---------------------------------------------------------------------------
# CIDR / IP helpers
# ---------------------------------------------------------------------------


def is_cidr(value: str) -> bool:
    """Return True if *value* is valid CIDR notation (e.g. '10.0.0.0/24')."""
    try:
        ipaddress.ip_network(value, strict=False)
        return "/" in value
    except (ValueError, TypeError):
        return False


def derive_probe_ip(cidr_str: str) -> Optional[str]:
    """Return ``network_address + 1`` as a representative host IP, or None."""
    try:
        net = ipaddress.ip_network(cidr_str, strict=False)
        hosts = list(net.hosts())
        if hosts:
            return str(hosts[0])
        return None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Derivation registry
# ---------------------------------------------------------------------------

# Each entry: (role_check, id_check, derive_fn)
#   role_check(role: str) -> bool
#   id_check(component_id: str) -> bool
#   derive_fn(component_id: str) -> Dict[str, str]
_DERIVATION_RULES: List[Tuple[Callable, Callable, Callable]] = []


def register_derivation(
    role_check: Callable[[str], bool],
    id_check: Callable[[str], bool],
    derive_fn: Callable[[str], Dict[str, str]],
) -> None:
    """Register a value derivation rule."""
    _DERIVATION_RULES.append((role_check, id_check, derive_fn))


def derive_component_metadata(component: Component) -> Dict[str, str]:
    """Apply all matching derivation rules to *component*, return derived metadata."""
    derived: Dict[str, str] = {}
    for role_check, id_check, derive_fn in _DERIVATION_RULES:
        try:
            if role_check(component.role) and id_check(component.id):
                derived.update(derive_fn(component.id))
        except Exception as exc:
            logger.warning(f"Derivation rule failed for {component.id}: {exc}")
    return derived


# ---------------------------------------------------------------------------
# Built-in derivation rules
# ---------------------------------------------------------------------------

# Rule 1: CIDR -> representative host IP (network + 1)
register_derivation(
    role_check=lambda r: is_target_role(r) or r in ("subnet", "network"),
    id_check=is_cidr,
    derive_fn=lambda cidr: (
        {"cidr": cidr, "probe_ip": derive_probe_ip(cidr)}
        if derive_probe_ip(cidr)
        else {"cidr": cidr}
    ),
)

# ---------------------------------------------------------------------------
# Metadata key -> argument key mapping
# ---------------------------------------------------------------------------

# Maps target arg keys to metadata keys that can provide a derived value.
# Order matters: first match wins.
_METADATA_FOR_ARG: Dict[str, List[str]] = {
    "ip": ["probe_ip"],
    "address": ["probe_ip"],
    "target": ["probe_ip", "cidr"],
    "destination": ["probe_ip", "cidr"],
    "subnet": ["cidr"],
    "network": ["cidr"],
    "cidr": ["cidr"],
}


# ---------------------------------------------------------------------------
# Core sanitizer
# ---------------------------------------------------------------------------


def sanitize_tool_args(
    tool_args: Dict[str, Any],
    component: Component,
) -> Dict[str, Any]:
    """
    Type-aware argument injection.

    - EXECUTOR arg keys (device, host, ...) <- comp.id only if comp has executor role
    - TARGET arg keys (target, ip, subnet, ...) <- first checks comp.metadata for
      a derived value matching the arg's semantic type, falls back to comp.id only
      if comp has target role
    - Only replaces placeholder values (empty string, ``<device>``, etc.)

    Returns the (mutated) *tool_args* dict.
    """
    comp_is_executor = is_executor_role(component.role)
    comp_is_target = is_target_role(component.role)
    metadata = component.metadata or {}

    for key in list(tool_args.keys()):
        current_val = str(tool_args[key]).strip()

        # Only replace placeholders
        if current_val not in PLACEHOLDER_VALUES:
            continue

        # --- Executor keys ---
        if key in EXECUTOR_ARG_KEYS:
            if comp_is_executor:
                tool_args[key] = component.id
                logger.debug(f"Sanitizer: {key} <- '{component.id}' (executor)")
            continue

        # --- Target keys ---
        if key in TARGET_ARG_KEYS:
            # 1. Try derived metadata matching the arg's semantic type
            candidates = _METADATA_FOR_ARG.get(key, [])
            injected = False
            for meta_key in candidates:
                if meta_key in metadata and metadata[meta_key]:
                    tool_args[key] = metadata[meta_key]
                    logger.debug(f"Sanitizer: {key} <- metadata['{meta_key}']={metadata[meta_key]}")
                    injected = True
                    break

            # 2. Fallback: comp.id if component is a target
            if not injected and comp_is_target:
                tool_args[key] = component.id
                logger.debug(f"Sanitizer: {key} <- '{component.id}' (target fallback)")
            continue

    return tool_args
