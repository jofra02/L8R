"""Deterministic control evaluators (rules and parsers).

A rule/parser receives the normalized evidence map ``{step_id: payload}``
(payloads as produced by the step normalizers: ``{"results": ..., "meta":
...}``) plus the control's ``params`` and returns an ``EvalOutcome``.

Evaluators must be pure, deterministic and defensive: they never raise on
malformed evidence — they return ``insufficient_evidence`` or ``error``.
Missing evidence is NEVER a ``fail`` (spec rule).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class EvalOutcome:
    status: str  # pass|fail|warning|not_applicable|insufficient_evidence|error
    explanation: str
    recommendation: Optional[str] = None
    evidence_refs: List[str] = field(default_factory=list)
    confidence: float = 1.0


Evaluator = Callable[[Dict[str, Any], Dict[str, Any]], EvalOutcome]

_RULES: Dict[str, Evaluator] = {}
_PARSERS: Dict[str, Evaluator] = {}


def register_rule(name: str):
    def deco(fn: Evaluator):
        if name in _RULES:
            raise ValueError(f"duplicate rule '{name}'")
        _RULES[name] = fn
        return fn
    return deco


def register_parser(name: str):
    def deco(fn: Evaluator):
        if name in _PARSERS:
            raise ValueError(f"duplicate parser '{name}'")
        _PARSERS[name] = fn
        return fn
    return deco


def get_rule(name: str) -> Evaluator:
    try:
        return _RULES[name]
    except KeyError:
        raise KeyError(f"unknown rule '{name}'") from None


def get_parser(name: str) -> Evaluator:
    try:
        return _PARSERS[name]
    except KeyError:
        raise KeyError(f"unknown parser '{name}'") from None


def known_rules() -> List[str]:
    return sorted(_RULES)


def known_parsers() -> List[str]:
    return sorted(_PARSERS)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _results(evidence: Dict[str, Any], step_id: str) -> Any:
    payload = evidence.get(step_id)
    if not isinstance(payload, dict):
        return None
    return payload.get("results")

def _meta(evidence: Dict[str, Any], step_id: str) -> Dict[str, Any]:
    payload = evidence.get(step_id)
    if isinstance(payload, dict) and isinstance(payload.get("meta"), dict):
        return payload["meta"]
    return {}


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _tokens(value: Any) -> List[str]:
    """FortiOS multi-value fields arrive as space-separated strings or lists."""
    if isinstance(value, str):
        return value.split()
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append(str(item.get("name", item)))
            else:
                out.append(str(item))
        return out
    return []


def _parse_version(text: str) -> Optional[tuple]:
    """'v7.4.5,build2662...' | 'v7.4.5' | '7.4.5' -> (7, 4)."""
    if not text:
        return None
    cleaned = text.strip().lstrip("vV").split(",")[0]
    parts = cleaned.split(".")
    try:
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return None


_UNRESTRICTED_HOSTS = {"0.0.0.0 0.0.0.0", "0.0.0.0/0", "::/0", ""}


def _admin_is_unrestricted(admin: Dict[str, Any]) -> bool:
    """True when no trusthost field restricts the account (absent fields included)."""
    for key, value in admin.items():
        if key.startswith("trusthost") or key.startswith("ip6-trusthost"):
            if isinstance(value, str) and value.strip() and value.strip() not in _UNRESTRICTED_HOSTS:
                return False
    return True


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

@register_parser("fortigate.fortios_version_supported")
def fortios_version_supported(evidence: Dict[str, Any], params: Dict[str, Any]) -> EvalOutcome:
    meta = _meta(evidence, "system_status")
    results = _results(evidence, "system_status")
    version_text = meta.get("version") or (
        results.get("version") if isinstance(results, dict) else None
    )
    if not version_text:
        return EvalOutcome(
            status="insufficient_evidence",
            explanation="FortiOS version not present in system_status evidence.",
            evidence_refs=["system_status"],
        )

    running = _parse_version(str(version_text))
    minimum = _parse_version(str(params.get("minimum_supported", "7.2")))
    if not running or not minimum:
        return EvalOutcome(
            status="error",
            explanation=f"Could not parse FortiOS version '{version_text}'.",
            evidence_refs=["system_status"],
        )

    if running >= minimum:
        return EvalOutcome(
            status="pass",
            explanation=f"FortiOS {version_text} meets the minimum supported train "
                        f"{params.get('minimum_supported')}.",
            evidence_refs=["system_status"],
        )
    return EvalOutcome(
        status="fail",
        explanation=f"FortiOS {version_text} is below the minimum supported train "
                    f"{params.get('minimum_supported')}.",
        recommendation="Plan an upgrade to a supported FortiOS release train.",
        evidence_refs=["system_status"],
    )


@register_parser("fortigate.policies_without_logging")
def policies_without_logging(evidence: Dict[str, Any], params: Dict[str, Any]) -> EvalOutcome:
    policies = _results(evidence, "firewall_policies")
    if not isinstance(policies, list):
        return EvalOutcome(
            status="insufficient_evidence",
            explanation="Firewall policy list not available.",
            evidence_refs=["firewall_policies"],
        )

    offending = [
        str(p.get("policyid", "?")) for p in policies
        if isinstance(p, dict)
        and p.get("status", "enable") == "enable"
        and p.get("action", "accept") == "accept"
        and p.get("logtraffic", "utm") == "disable"
    ]
    if not offending:
        return EvalOutcome(
            status="pass",
            explanation=f"All {len(policies)} enabled accept policies have traffic logging.",
            evidence_refs=["firewall_policies"],
        )
    return EvalOutcome(
        status="fail",
        explanation=f"{len(offending)} enabled accept policies have logging disabled: "
                    f"policy ids {', '.join(offending[:20])}"
                    + (" (truncated)" if len(offending) > 20 else "") + ".",
        recommendation="Enable traffic logging (logtraffic) on the listed policies.",
        evidence_refs=["firewall_policies"],
    )


@register_parser("fortigate.overly_permissive_policies")
def overly_permissive_policies(evidence: Dict[str, Any], params: Dict[str, Any]) -> EvalOutcome:
    policies = _results(evidence, "firewall_policies")
    if not isinstance(policies, list):
        return EvalOutcome(
            status="insufficient_evidence",
            explanation="Firewall policy list not available.",
            evidence_refs=["firewall_policies"],
        )

    def is_all(field_value: Any) -> bool:
        names = [n.lower() for n in _tokens(field_value)]
        return "all" in names

    offending = [
        str(p.get("policyid", "?")) for p in policies
        if isinstance(p, dict)
        and p.get("status", "enable") == "enable"
        and p.get("action", "accept") == "accept"
        and is_all(p.get("srcaddr"))
        and is_all(p.get("dstaddr"))
        and is_all(p.get("service"))
    ]
    if not offending:
        return EvalOutcome(
            status="pass",
            explanation="No enabled accept policy matches any-source/any-destination/ALL-services.",
            evidence_refs=["firewall_policies"],
        )
    return EvalOutcome(
        status="fail",
        explanation=f"{len(offending)} enabled accept policies are any/any/ALL: "
                    f"policy ids {', '.join(offending[:20])}"
                    + (" (truncated)" if len(offending) > 20 else "") + ".",
        recommendation="Replace any/any/ALL policies with specific source, destination "
                       "and service objects (deny by default).",
        evidence_refs=["firewall_policies"],
    )


_PROFILE_FIELDS = (
    "av-profile", "webfilter-profile", "dnsfilter-profile",
    "ips-sensor", "application-list", "ssl-ssh-profile", "file-filter-profile",
)


@register_parser("fortigate.policies_without_profiles")
def policies_without_profiles(evidence: Dict[str, Any], params: Dict[str, Any]) -> EvalOutcome:
    policies = _results(evidence, "firewall_policies")
    if not isinstance(policies, list):
        return EvalOutcome(
            status="insufficient_evidence",
            explanation="Firewall policy list not available.",
            evidence_refs=["firewall_policies"],
        )

    accept = [
        p for p in policies
        if isinstance(p, dict)
        and p.get("status", "enable") == "enable"
        and p.get("action", "accept") == "accept"
    ]
    offending = [
        str(p.get("policyid", "?")) for p in accept
        if not any(p.get(f) for f in _PROFILE_FIELDS)
    ]
    if not accept:
        return EvalOutcome(
            status="not_applicable",
            explanation="No enabled accept policies present.",
            evidence_refs=["firewall_policies"],
        )
    if not offending:
        return EvalOutcome(
            status="pass",
            explanation=f"All {len(accept)} enabled accept policies apply at least one security profile.",
            evidence_refs=["firewall_policies"],
        )
    return EvalOutcome(
        status="warning",
        explanation=f"{len(offending)} of {len(accept)} enabled accept policies apply no "
                    f"security profile: policy ids {', '.join(offending[:20])}"
                    + (" (truncated)" if len(offending) > 20 else "") + ".",
        recommendation="Apply IPS/AV/web-filter profiles according to each flow's exposure.",
        evidence_refs=["firewall_policies"],
    )


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

@register_rule("fortigate.trusted_hosts_rule")
def trusted_hosts_rule(evidence: Dict[str, Any], params: Dict[str, Any]) -> EvalOutcome:
    admins = _results(evidence, "admin_users")
    if not isinstance(admins, list) or not admins:
        return EvalOutcome(
            status="insufficient_evidence",
            explanation="Administrator list not available.",
            evidence_refs=["admin_users"],
        )

    unrestricted = [
        str(a.get("name", "?")) for a in admins
        if isinstance(a, dict) and _admin_is_unrestricted(a)
    ]
    if not unrestricted:
        return EvalOutcome(
            status="pass",
            explanation=f"All {len(admins)} administrator accounts define trusted hosts.",
            evidence_refs=["admin_users"],
        )
    return EvalOutcome(
        status="fail",
        explanation=f"{len(unrestricted)} administrator accounts have no trusted hosts "
                    f"(reachable from any source): {', '.join(unrestricted)}.",
        recommendation="Configure trusted hosts limiting each admin account to "
                       "administrative source networks.",
        evidence_refs=["admin_users"],
    )


@register_rule("fortigate.remote_auth_rule")
def remote_auth_rule(evidence: Dict[str, Any], params: Dict[str, Any]) -> EvalOutcome:
    admins = _results(evidence, "admin_users")
    if not isinstance(admins, list) or not admins:
        return EvalOutcome(
            status="insufficient_evidence",
            explanation="Administrator list not available.",
            evidence_refs=["admin_users"],
        )

    remote = [a for a in admins if isinstance(a, dict) and a.get("remote-auth") == "enable"]
    refs = ["admin_users"]
    servers_present = False
    for step in ("radius_servers", "ldap_servers"):
        srv = _results(evidence, step)
        if isinstance(srv, list) and srv:
            servers_present = True
            refs.append(step)

    if remote:
        return EvalOutcome(
            status="pass",
            explanation=f"{len(remote)} of {len(admins)} administrator accounts use "
                        f"remote authentication.",
            evidence_refs=refs,
        )
    if servers_present:
        return EvalOutcome(
            status="warning",
            explanation="RADIUS/LDAP servers are configured but no administrator account "
                        "uses remote authentication.",
            recommendation="Bind administrator accounts to the central identity source; "
                           "keep one controlled local break-glass account.",
            evidence_refs=refs,
        )
    return EvalOutcome(
        status="warning",
        explanation="All administrator accounts are local-only; no central "
                    "authentication source is in use.",
        recommendation="Integrate administrator authentication with RADIUS/LDAP/SAML "
                       "and enforce MFA centrally.",
        evidence_refs=refs,
    )


@register_rule("fortigate.central_logging_rule")
def central_logging_rule(evidence: Dict[str, Any], params: Dict[str, Any]) -> EvalOutcome:
    faz = _results(evidence, "faz_setting")
    syslog = _results(evidence, "syslog_setting")
    if faz is None and syslog is None:
        return EvalOutcome(
            status="insufficient_evidence",
            explanation="Neither FortiAnalyzer nor syslog settings could be collected.",
            evidence_refs=["faz_setting", "syslog_setting"],
        )

    destinations = []
    if isinstance(faz, dict) and faz.get("status") == "enable" and faz.get("server"):
        destinations.append(f"FortiAnalyzer ({faz.get('server')})")
    if isinstance(syslog, dict) and syslog.get("status") == "enable" and syslog.get("server"):
        destinations.append(f"syslog ({syslog.get('server')})")

    refs = [s for s in ("faz_setting", "syslog_setting") if evidence.get(s) is not None]
    if destinations:
        return EvalOutcome(
            status="pass",
            explanation=f"Central logging enabled: {', '.join(destinations)}.",
            evidence_refs=refs,
        )
    return EvalOutcome(
        status="fail",
        explanation="No off-box log destination is enabled (FortiAnalyzer and syslog "
                    "are both disabled or unset).",
        recommendation="Forward traffic, UTM, event and admin logs to FortiAnalyzer "
                       "or a syslog collector.",
        evidence_refs=refs,
    )


@register_rule("fortigate.ntp_rule")
def ntp_rule(evidence: Dict[str, Any], params: Dict[str, Any]) -> EvalOutcome:
    ntp = _results(evidence, "ntp_config")
    if not isinstance(ntp, dict):
        return EvalOutcome(
            status="insufficient_evidence",
            explanation="NTP configuration not available.",
            evidence_refs=["ntp_config"],
        )

    refs = ["ntp_config"]
    sync_enabled = ntp.get("ntpsync") == "enable"
    servers = _as_list(ntp.get("ntpserver")) if ntp.get("type") != "fortiguard" else ["FortiGuard"]
    if not sync_enabled:
        return EvalOutcome(
            status="fail",
            explanation="NTP synchronization (ntpsync) is disabled.",
            recommendation="Enable NTP against trusted internal or authorized sources.",
            evidence_refs=refs,
        )
    if not servers:
        return EvalOutcome(
            status="fail",
            explanation="NTP synchronization is enabled but no NTP server is configured.",
            recommendation="Configure trusted NTP servers.",
            evidence_refs=refs,
        )

    status = _results(evidence, "ntp_status")
    if status is not None:
        refs.append("ntp_status")
        entries = status if isinstance(status, list) else [status]
        synced = any(
            isinstance(e, dict) and (e.get("selected") or e.get("reachable"))
            for e in entries
        )
        if not synced:
            return EvalOutcome(
                status="warning",
                explanation="NTP is configured but no server is currently selected/reachable.",
                recommendation="Verify reachability of the configured NTP sources.",
                evidence_refs=refs,
            )
    return EvalOutcome(
        status="pass",
        explanation=f"NTP enabled with {len(servers)} configured source(s).",
        evidence_refs=refs,
    )


@register_rule("fortigate.ha_status_rule")
def ha_status_rule(evidence: Dict[str, Any], params: Dict[str, Any]) -> EvalOutcome:
    ha = _results(evidence, "ha_config")
    if not isinstance(ha, dict):
        return EvalOutcome(
            status="insufficient_evidence",
            explanation="HA configuration not available.",
            evidence_refs=["ha_config"],
        )

    mode = str(ha.get("mode", "standalone")).lower()
    if mode in ("standalone", "none", ""):
        return EvalOutcome(
            status="not_applicable",
            explanation="Device operates standalone (no HA configured).",
            evidence_refs=["ha_config"],
        )

    refs = ["ha_config"]
    stats = _results(evidence, "ha_status")
    if stats is not None:
        refs.append("ha_status")
        members = stats if isinstance(stats, list) else [stats]
        out_of_sync = [
            str(m.get("hostname", m.get("serial_no", "?"))) for m in members
            if isinstance(m, dict) and m.get("sync_status") not in (None, "synchronized", "in-sync", 1, True)
        ]
        if out_of_sync:
            return EvalOutcome(
                status="fail",
                explanation=f"HA mode '{mode}' with members out of sync: {', '.join(out_of_sync)}.",
                recommendation="Investigate HA synchronization before any failover event.",
                evidence_refs=refs,
            )
        return EvalOutcome(
            status="pass",
            explanation=f"HA mode '{mode}' with {len(members)} member(s) synchronized.",
            evidence_refs=refs,
        )
    return EvalOutcome(
        status="warning",
        explanation=f"HA mode '{mode}' is configured but member synchronization state "
                    "could not be verified.",
        recommendation="Verify HA member synchronization status.",
        evidence_refs=refs,
    )


_INSECURE_ACCESS = {"http", "telnet"}
_MGMT_ACCESS = {"http", "https", "ssh", "telnet", "snmp"}


@register_rule("fortigate.management_access_rule")
def management_access_rule(evidence: Dict[str, Any], params: Dict[str, Any]) -> EvalOutcome:
    """Deterministic half of FGT-MGMT-001 (the LLM enriches/adjudicates)."""
    interfaces = _results(evidence, "interfaces")
    if not isinstance(interfaces, list):
        return EvalOutcome(
            status="insufficient_evidence",
            explanation="Interface configuration not available.",
            evidence_refs=["interfaces"],
        )

    insecure: List[str] = []
    wan_exposed: List[str] = []
    for intf in interfaces:
        if not isinstance(intf, dict) or intf.get("status") == "down":
            continue
        name = str(intf.get("name", "?"))
        access = {t.lower() for t in _tokens(intf.get("allowaccess"))}
        if access & _INSECURE_ACCESS:
            insecure.append(f"{name} ({', '.join(sorted(access & _INSECURE_ACCESS))})")
        if str(intf.get("role", "")).lower() == "wan" and access & _MGMT_ACCESS:
            wan_exposed.append(f"{name} ({', '.join(sorted(access & _MGMT_ACCESS))})")

    refs = ["interfaces", "system_global", "admin_users"]
    problems = []
    if insecure:
        problems.append(f"insecure management protocols enabled on: {'; '.join(insecure)}")
    if wan_exposed:
        problems.append(f"management access exposed on WAN-role interfaces: {'; '.join(wan_exposed)}")

    if wan_exposed:
        return EvalOutcome(
            status="fail",
            explanation="Administrative exposure detected — " + "; ".join(problems) + ".",
            recommendation="Remove management allowaccess from WAN interfaces and "
                           "disable HTTP/Telnet everywhere.",
            evidence_refs=refs,
        )
    if insecure:
        return EvalOutcome(
            status="warning",
            explanation="Insecure management protocols detected — " + "; ".join(problems) + ".",
            recommendation="Disable HTTP and Telnet management access.",
            evidence_refs=refs,
        )
    return EvalOutcome(
        status="pass",
        explanation="No insecure management protocols and no management access on "
                    "WAN-role interfaces.",
        evidence_refs=refs,
    )
