"""Skill drift guard (no DB, no network).

Domain skills anchor exact gateway tool names so the Engineer can execute them
without a catalog hit ("search is discovery, not permission"). That contract
breaks silently if a skill references a tool that no longer exists in the
gateway baseline, or if DOMAIN_SKILL_MAP points to a skill file that was
renamed. This test pins both.

Run: uv run pytest src/testing/test_skill_drift.py
"""

import re
from pathlib import Path

from src.agents.engineer_tools import DOMAIN_SKILL_MAP, SKILLS_DIR

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "mcp_gateway" / "baseline_tools.txt"

# Backtick-quoted gateway tool names inside skill files; a trailing `*` marks a
# prefix family (e.g. `fgt74_cmdb_registration_post_forticare_*`). Pack prefixes
# are versioned (fgt74, fedr62, ...), so match any fgt/fedr prefix variant.
ANCHOR_RE = re.compile(r"`((?:fgt|fedr)[a-z0-9]*_[a-z0-9_]+\*?)`")


def test_domain_skill_map_files_exist():
    missing = sorted(
        {filename for filename in DOMAIN_SKILL_MAP.values() if not (SKILLS_DIR / filename).exists()}
    )
    assert not missing, f"DOMAIN_SKILL_MAP points to missing skill files: {missing}"


def test_skill_anchors_exist_in_baseline():
    baseline = {line for line in BASELINE.read_text(encoding="utf-8").splitlines() if line}

    unresolved = []
    for skill_file in sorted(SKILLS_DIR.glob("*.md")):
        for anchor in ANCHOR_RE.findall(skill_file.read_text(encoding="utf-8")):
            if anchor.endswith("*"):
                prefix = anchor[:-1]
                if not any(name.startswith(prefix) for name in baseline):
                    unresolved.append((skill_file.name, anchor))
            elif anchor not in baseline:
                unresolved.append((skill_file.name, anchor))

    assert not unresolved, (
        "Skill anchors not found in mcp_gateway/baseline_tools.txt "
        f"(skill, anchor): {unresolved}"
    )
