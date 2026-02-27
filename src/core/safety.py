"""Shared safety utilities for tool execution governance."""

from typing import Any, Dict
from src.config import settings
import logging

logger = logging.getLogger(__name__)


def is_safe_tool(tool_name: str, tool_args: Dict[str, Any]) -> bool:
    """
    Checks if tool usage is safe against blocked keywords.
    Shared across all agents that execute tools.
    """
    blocked = settings.SAFETY_BLOCKED_KEYWORDS

    # Check Name
    for kw in blocked:
        if kw in tool_name.lower():
            logger.warning(f"Safety Block: Tool '{tool_name}' blocked by keyword '{kw}'")
            return False

    # Check Args (e.g. "command": "execute ...")
    for key, val in tool_args.items():
        if isinstance(val, str):
            for kw in blocked:
                if kw in val.lower():
                    logger.warning(f"Safety Block: Tool '{tool_name}' arg '{key}'='{val}' blocked by keyword '{kw}'")
                    return False
    return True


async def is_tool_allowed_for_tenant(tool_name: str, customer_id: str) -> bool:
    """
    Check if a tool is allowed for a given tenant based on CapabilityScope ORM.
    Falls back to allow-all if no scopes are defined (backward compatible).
    """
    try:
        from src.core.database import async_session
        from src.core.orm import CapabilityScope
        from sqlalchemy import select
        import fnmatch

        async with async_session() as session:
            result = await session.execute(
                select(CapabilityScope).where(CapabilityScope.customer_id == customer_id)
            )
            scopes = result.scalars().all()

            # No scopes defined → allow all (backward compat)
            if not scopes:
                return True

            # Check if tool_name matches any allowed_tools pattern
            for scope in scopes:
                for pattern in scope.allowed_tools:
                    if fnmatch.fnmatch(tool_name.lower(), pattern.lower()):
                        return True

            logger.warning(f"Governance Block: Tool '{tool_name}' not allowed for tenant '{customer_id}'")
            return False

    except Exception as e:
        # DB not available or schema missing → fail-open (allow)
        logger.warning(f"Governance check failed (allowing): {e}")
        return True
