"""Safety name-filter regression over the frozen gateway baseline.

The 2026-07 token-matching fix must change the verdict ONLY as follows
versus the legacy substring filter:
- newly ALLOWED: exactly 3 read-only GET tools (false positives, incl. the
  "format" in vm_inFORMATion case);
- newly BLOCKED: *_put_* config writers (mutating tools that previously
  slipped through — closes the documented open finding) plus nothing else.

Run: uv run pytest src/testing/test_safety_regression.py
"""

from pathlib import Path

from src.config import settings
from src.core.safety import _name_blocked_by, is_safe_tool

BASELINE = Path(__file__).resolve().parents[2] / "mcp_gateway" / "baseline_tools.txt"

# Legacy behavior frozen at the moment of the fix (old keyword list, pure
# substring matching) — the reference for the regression delta.
LEGACY_NAME_KEYWORDS = [
    "update", "create", "upload", "upgrade", "isolate", "uninstall",
    "remediate", "terminate", "set_", "reset", "assign", "clone",
    "transfer", "import", "toggle", "release", "move", "stop",
]

EXPECTED_NEWLY_ALLOWED = {
    "fgt74_monitor_sys_get_vm_information",          # format ⊂ inFORMATion
    "fgt74_cmdb_sys_get_system_autoupdate_schedule",  # update ⊂ autoUPDATE (GET)
    "fgt74_cmdb_sys_get_system_autoupdate_tunneling",
}


def legacy_blocked(name: str) -> bool:
    lowered = name.lower()
    for kw in settings.SAFETY_BLOCKED_KEYWORDS + LEGACY_NAME_KEYWORDS:
        if kw in lowered:
            return True
    return False


def load_baseline() -> list[str]:
    return [l.strip() for l in BASELINE.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_baseline_exists():
    assert BASELINE.exists()
    assert len(load_baseline()) == 2776


def test_newly_allowed_is_exactly_the_three_false_positives():
    names = load_baseline()
    newly_allowed = {n for n in names if legacy_blocked(n) and _name_blocked_by(n) is None}
    assert newly_allowed == EXPECTED_NEWLY_ALLOWED
    # and every one of them is a read-only GET
    assert all("_get_" in n for n in newly_allowed)


def test_newly_blocked_are_only_mutating_puts_and_vmlicense():
    names = load_baseline()
    newly_blocked = [n for n in names if not legacy_blocked(n) and _name_blocked_by(n)]
    assert newly_blocked, "the PUT hardening must block previously-allowed writers"
    unexpected = [n for n in newly_blocked
                  if "_put_" not in n and not n.endswith("_put") and "vmlicense" not in n]
    assert not unexpected, f"unexpected newly blocked: {unexpected[:5]}"


def test_known_mutating_tools_stay_blocked():
    for name in (
        "fgt74_monitor_sys_post_logdisk_format",
        "fedr62_mgmt_sendable_entities_set_mail_format",
        "fedr62_mgmt_system_inventory_unisolate_collectors",
        "fgt74_monitor_user_post_device_remove",
        "fgt74_cmdb_sys_put_system_autoupdate_schedule",
        "fgt74_cmdb_sys_put_global",
        "fgt74_monitor_sys_post_vmlicense_download",
    ):
        assert not is_safe_tool(name, {}), f"{name} must be blocked"


def test_known_readonly_tools_stay_allowed():
    for name in (
        "fgt74_monitor_sys_get_status",
        "fgt74_monitor_lic_get_license_status",
        "fgt74_cmdb_log_get_feature_set",   # 'set_' keeps positional semantics
        "fedr62_mgmt_system_inventory_get_list_collectors",
        "fedr62_mgmt_administrator_get_admin_list_system_summary",
    ):
        assert is_safe_tool(name, {}), f"{name} must stay allowed"


def test_arg_value_matching_unchanged():
    assert not is_safe_tool("fgt74_monitor_sys_get_status", {"cmd": "execute reboot"})
    assert is_safe_tool("fgt74_monitor_sys_get_status", {"filter": "lastUpdateTime>0"})
