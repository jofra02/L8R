"""Reusable MCP tool execution helper.

Single entry point for calling an MCP gateway tool on behalf of a tenant,
shared by the Engineer agent (``engineer_tools.execute_tool``) and the
assessment Collection Engine. Centralizes the read-only guardrails:

    safety keyword filter -> tenant governance -> registry resolution ->
    optional strict read-only allowlist -> framework-side tenant injection ->
    (optionally time-limited) execution -> error classification

Auditing is intentionally NOT done here: the engineer path records
``ToolCallAuditORM`` rows (keyed to agent runs) and the assessment path
records ``assessment_collection_executions`` rows — each caller owns its
own forensic record.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Strict read-only allowlist for deterministic (non-agent) execution paths.
# Applied on top of the global SAFETY_BLOCKED_KEYWORDS filter: the tool name
# must look like a GET-style operation and must not contain any mutating or
# active-operation marker.
READ_ONLY_REQUIRED_MARKER = "_get"
READ_ONLY_BLOCKED_MARKERS = (
    "_post_", "_put_", "_delete_", "_exec", "_reset", "_upload",
    "_download", "_create", "_update", "_upgrade", "_restore", "_import",
)


@dataclass
class MCPToolResult:
    """Outcome of a single MCP tool execution attempt."""

    ok: bool
    content: Any = None
    error: Optional[str] = None
    # One of: safety | authorization | not_found | read_only |
    #         timeout | connection | unknown
    error_type: Optional[str] = None
    # "preflight" = blocked before dispatch; "execute" = the call was dispatched.
    stage: str = "execute"
    duration_ms: int = 0
    # Args actually sent to the gateway (after framework tenant injection).
    final_args: Dict[str, Any] = field(default_factory=dict)

    @property
    def preflight_failure(self) -> bool:
        """True when the tool was never executed (blocked before dispatch)."""
        return self.stage == "preflight"

    @property
    def gateway_error(self) -> bool:
        """True when the gateway executed the call but reported an error.

        The MCP client flattens ``CallToolResult.isError`` into a text payload
        prefixed with ``Error:`` — the transport call itself succeeds.
        """
        return self.ok and isinstance(self.content, str) and self.content.startswith("Error:")


def is_read_only_tool_name(tool_name: str) -> bool:
    """Strict name-based read-only check (assessment allowlist)."""
    name = tool_name.lower()
    if READ_ONLY_REQUIRED_MARKER not in name:
        return False
    return not any(marker in name for marker in READ_ONLY_BLOCKED_MARKERS)


async def _canonicalize_device(value: Any, customer_id: str) -> Any:
    """Resolve a caller-supplied ``device`` selector to the asset id.

    Gateway devices are registered with ``id = asset.id``; ``ref`` is a human
    slug that must never route. Callers (the Engineer LLM in particular) may
    pass either — a tenant-scoped lookup maps ref -> id. Values matching no
    asset pass through untouched: they may address hand-maintained gateway
    inventory entries the app has no record of.
    """
    if not isinstance(value, str) or not value:
        return value
    try:
        from sqlalchemy import or_, select

        from src.core.database import async_session_factory
        from src.core.orm import AssetORM

        async with async_session_factory() as session:
            row = (await session.execute(
                select(AssetORM.id).where(
                    AssetORM.customer_id == customer_id,
                    or_(AssetORM.id == value, AssetORM.ref == value),
                    AssetORM.deleted_at.is_(None),
                    AssetORM.managed.is_(True),
                ).limit(1)
            )).scalar_one_or_none()
    except Exception as e:  # noqa: BLE001 — resolution is best-effort
        logger.warning(f"device selector resolution failed for '{value}': {e}")
        return value
    if row is not None and row != value:
        logger.info(f"device selector '{value}' resolved to asset id '{row}'")
        return row
    return value


def _classify_exception(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    msg = str(exc).lower()
    if isinstance(exc, (ConnectionError, OSError)) or "connect" in msg or "unreachable" in msg:
        return "connection"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "401" in msg or "403" in msg or "unauthorized" in msg or "forbidden" in msg:
        return "authorization"
    return "unknown"


async def execute_mcp_tool(
    tool_name: str,
    args: Dict[str, Any],
    customer_id: str,
    *,
    enforce_read_only: bool = False,
    timeout_s: Optional[float] = None,
) -> MCPToolResult:
    """Execute one MCP tool for a tenant through the shared guardrail pipeline.

    Args:
        tool_name: Exact tool name as registered in the CapabilityRegistry.
        args: Tool arguments. Not mutated; ``tenant`` is always overwritten
              framework-side with ``customer_id`` in the dispatched copy.
        customer_id: Tenant the call is executed for (authoritative).
        enforce_read_only: Additionally require a GET-style tool name
              (deterministic paths — assessments — must set this).
        timeout_s: Optional hard wall-clock limit for the gateway call.
    """
    from src.core.registry import CapabilityRegistry
    from src.core.safety import is_safe_tool, is_tool_allowed_for_tenant

    if not is_safe_tool(tool_name, args):
        return MCPToolResult(
            ok=False, error_type="safety", stage="preflight",
            error=f"Tool '{tool_name}' blocked by safety policy.",
        )

    if enforce_read_only and not is_read_only_tool_name(tool_name):
        return MCPToolResult(
            ok=False, error_type="read_only", stage="preflight",
            error=f"Tool '{tool_name}' is not in the read-only allowlist.",
        )

    if not await is_tool_allowed_for_tenant(tool_name, customer_id):
        return MCPToolResult(
            ok=False, error_type="authorization", stage="preflight",
            error=f"Tool '{tool_name}' is not allowed for this tenant.",
        )

    tool_obj = CapabilityRegistry.get_tool(tool_name)
    if not tool_obj:
        return MCPToolResult(
            ok=False, error_type="not_found", stage="preflight",
            error=f"Tool '{tool_name}' not found in registry.",
        )

    # Tenant routing: framework-injected selector so the gateway routes against
    # this tenant's inventory. Never caller/LLM-supplied — always overwritten.
    # Device routing: canonicalized to the asset id (ref accepted as alias).
    final_args = dict(args)
    if "device" in final_args:
        final_args["device"] = await _canonicalize_device(
            final_args["device"], customer_id
        )
    final_args["tenant"] = customer_id

    started = time.monotonic()
    try:
        coro = tool_obj.run(**final_args)
        if timeout_s is not None:
            result = await asyncio.wait_for(coro, timeout=timeout_s)
        else:
            result = await coro
    except asyncio.CancelledError:
        raise
    except BaseException as e:  # noqa: BLE001 — classified, never swallowed silently
        duration_ms = int((time.monotonic() - started) * 1000)
        error_type = _classify_exception(e)
        logger.warning(
            f"MCP tool '{tool_name}' failed ({error_type}) after {duration_ms}ms: {e}"
        )
        return MCPToolResult(
            ok=False, error=str(e), error_type=error_type,
            duration_ms=duration_ms, final_args=final_args,
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    return MCPToolResult(
        ok=True, content=result, duration_ms=duration_ms, final_args=final_args,
    )
