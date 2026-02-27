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
