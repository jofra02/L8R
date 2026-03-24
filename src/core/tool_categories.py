"""
Tool Category Taxonomy and Relatedness Map.

Single source of truth for IT operational domain categories used in
tool indexing (LLM-driven assignment) and tool retrieval (cascading search).

Data is loaded from data/tool_categories.yaml so any pipeline can consume
the taxonomy without importing this Python module.
"""

import yaml
from pathlib import Path
from typing import FrozenSet, List

_DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "tool_categories.yaml"


def _load_taxonomy() -> dict:
    with open(_DATA_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_DATA = _load_taxonomy()

TOOL_CATEGORIES: dict[str, str] = _DATA["categories"]
CATEGORY_RELATEDNESS: dict[str, list[str]] = _DATA["relatedness"]
_GROUP_MAP: dict[str, list[str]] = _DATA["groups"]
_VALID_SLUGS: FrozenSet[str] = frozenset(TOOL_CATEGORIES.keys())


def get_related_categories(category: str) -> List[str]:
    """Return related categories for the given slug, or empty list if unknown."""
    return CATEGORY_RELATEDNESS.get(category, [])


def get_all_category_slugs() -> FrozenSet[str]:
    """Return the full set of valid category slugs."""
    return _VALID_SLUGS


def get_categories_prompt_block() -> str:
    """Build a compact category list for injection into LLM prompts.

    Groups categories by domain for readability. ~300 tokens.
    """
    lines = []
    for group_name, slugs in _GROUP_MAP.items():
        lines.append(f"  {group_name}: {', '.join(slugs)}")
    return "TOOL CATEGORIES:\n" + "\n".join(lines)
