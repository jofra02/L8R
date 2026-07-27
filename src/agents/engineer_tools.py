"""Meta-tools for the Engineer agent.

Factory function creates LangChain tools with runtime context (customer_id,
run_id, etc.) bound via closure. These are the only tools the Engineer agent
needs to interact with the entire platform.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from src.core.models import (
    ClientContext, TopologyNode, TopologyEdge, EvidenceSnapshot,
)
from src.core.topology_utils import seed_topology_from_context

logger = logging.getLogger(__name__)

# Enum values shown per parameter in catalog results. Enums are what save the
# agent blind-guess round-trips (each failed call costs a full tool cycle), but
# unbounded lists would bloat the context — cap and elide with a count.
_ENUM_DISPLAY_CAP = 12


def _render_param_lines(schema: Dict[str, Any]) -> List[str]:
    """Render a tool's args schema as one compact line per parameter.

    Surfaces the constraints the agent needs to build a valid call on the
    first attempt — type, format, enum values, required flag — alongside the
    parameter description. Schemas indexed before raw-inputSchema capture have
    typeless properties; those degrade gracefully to name + description.
    """
    props = (schema or {}).get("properties", {})
    required = set((schema or {}).get("required") or [])
    if not props:
        return []
    lines = ["Parameters:"]
    for pname, pinfo in props.items():
        bits = []
        ptype = pinfo.get("type", "")
        if ptype == "array":
            item_type = (pinfo.get("items") or {}).get("type")
            ptype = f"array of {item_type}" if item_type else "array"
        fmt = pinfo.get("format")
        if ptype:
            bits.append(f"{ptype} ({fmt})" if fmt else ptype)
        enum = pinfo.get("enum")
        if enum:
            shown = "|".join(str(v) for v in enum[:_ENUM_DISPLAY_CAP])
            if len(enum) > _ENUM_DISPLAY_CAP:
                shown += f"|... +{len(enum) - _ENUM_DISPLAY_CAP} more"
            bits.append(f"one of: {shown}")
        req_tag = " (REQUIRED)" if pname in required else ""
        type_note = f" [{', '.join(bits)}]" if bits else ""
        pdesc = pinfo.get("description", pinfo.get("title", pname))
        lines.append(f"  - {pname}{req_tag}{type_note}: {pdesc}")
    return lines


async def _audit_tool_call(
    run_id: str, customer_id: str, tool_name: str, args: Dict[str, Any],
    status: str, error: Optional[str], started_at: datetime,
    result_meta: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort tool_calls_audit record (parity with AdaptiveExecutor's audit).

    The engineer's direct execution path bypasses AdaptiveExecutor, which is
    where tool calls were audited — without this, engineer runs leave
    tool_calls_audit empty and forensics go blind.
    """
    if not run_id:
        return
    try:
        from src.core.database import async_session_factory
        from src.core.orm import ToolCallAuditORM
        async with async_session_factory() as session:
            session.add(ToolCallAuditORM(
                id=str(uuid.uuid4()),
                run_id=run_id,
                customer_id=customer_id,
                tool_name=tool_name,
                args_redacted=args,
                result_meta=result_meta or {},
                status=status,
                error=error,
                started_at=started_at,
                ended_at=datetime.utcnow(),
            ))
            await session.commit()
    except Exception as e:
        logger.error(f"Engineer: failed to audit tool call {tool_name}: {e}")

# ---------------------------------------------------------------------------
# Domain skill mapping (keyword → filename)
# ---------------------------------------------------------------------------

SKILLS_DIR = Path(__file__).parent / "skills"

# Add new domain skills here; keys must map to files in src/agents/skills/
DOMAIN_SKILL_MAP = {
    # Networking
    "networking": "networking.md",
    "network": "networking.md",
    "routing": "networking.md",
    "switching": "networking.md",
    "interfaces": "networking.md",
    "bgp": "networking.md",
    "ospf": "networking.md",
    "dns": "networking.md",
    "dhcp": "networking.md",
    "qos": "networking.md",
    "vlan": "networking.md",
    "stp": "networking.md",
    "arp": "networking.md",
    "mtu": "networking.md",
    # Tool Catalog Search
    "tool_catalog": "tool_catalog.md",
    "tools": "tool_catalog.md",
    "tool_search": "tool_catalog.md",
    "catalog": "tool_catalog.md",
    # Licensing / entitlements (FortiGate appliance pack)
    "license": "fortigate_licensing.md",
    "licensing": "fortigate_licensing.md",
    "licenses": "fortigate_licensing.md",
    "entitlement": "fortigate_licensing.md",
    "entitlements": "fortigate_licensing.md",
    "subscription": "fortigate_licensing.md",
    "forticare": "fortigate_licensing.md",
    "fortiguard": "fortigate_licensing.md",
    # Logs / log retrieval (FortiGate appliance pack)
    "logs": "fortigate_logs.md",
    "log": "fortigate_logs.md",
    "logging": "fortigate_logs.md",
    "log_retrieval": "fortigate_logs.md",
    "syslog": "fortigate_logs.md",
    "web_logs": "fortigate_logs.md",
    "traffic_logs": "fortigate_logs.md",
    "browsing": "fortigate_logs.md",
    "browsing_history": "fortigate_logs.md",
    "web_history": "fortigate_logs.md",
    "navigation": "fortigate_logs.md",
    "webfilter": "fortigate_logs.md",
    "fortianalyzer": "fortigate_logs.md",
    "forticloud": "fortigate_logs.md",
    # Control-point flow verification (FortiGate appliance pack)
    "firewall": "flow_verification.md",
    "policy": "flow_verification.md",
    "policies": "flow_verification.md",
    "nat": "flow_verification.md",
    "block": "flow_verification.md",
    "blocked": "flow_verification.md",
    "blocking": "flow_verification.md",
    "connectivity": "flow_verification.md",
    "traffic": "flow_verification.md",
    "flow": "flow_verification.md",
    "flows": "flow_verification.md",
    "flow_verification": "flow_verification.md",
    "utm": "flow_verification.md",
    "inspection": "flow_verification.md",
    "app_control": "flow_verification.md",
    "application_control": "flow_verification.md",
    "vpn": "flow_verification.md",
    "tailscale": "flow_verification.md",
    "wireguard": "flow_verification.md",
    "zerotier": "flow_verification.md",
    # Endpoint security (FortiEDR appliance pack)
    "fortiedr": "fortiedr.md",
    "edr": "fortiedr.md",
    "xdr": "fortiedr.md",
    "endpoint": "fortiedr.md",
    "endpoints": "fortiedr.md",
    "endpoint_security": "fortiedr.md",
    "endpoint_protection": "fortiedr.md",
    "security_event": "fortiedr.md",
    "security_events": "fortiedr.md",
    "detection": "fortiedr.md",
    "detections": "fortiedr.md",
    "malware": "fortiedr.md",
    "ransomware": "fortiedr.md",
    "virus": "fortiedr.md",
    "antivirus": "fortiedr.md",
    "infection": "fortiedr.md",
    "infected": "fortiedr.md",
    "collector": "fortiedr.md",
    "collectors": "fortiedr.md",
    "threat": "fortiedr.md",
    "threats": "fortiedr.md",
    "threat_hunting": "fortiedr.md",
    "quarantine": "fortiedr.md",
    # Event triage / verdict (FortiEDR appliance pack)
    "triage": "fortiedr_triage.md",
    "event_triage": "fortiedr_triage.md",
    "alert_triage": "fortiedr_triage.md",
    "verdict": "fortiedr_triage.md",
    "malicious": "fortiedr_triage.md",
    "suspicious": "fortiedr_triage.md",
    "false_positive": "fortiedr_triage.md",
    "false_positives": "fortiedr_triage.md",
    "ioc": "fortiedr_triage.md",
    "iocs": "fortiedr_triage.md",
    "indicator_of_compromise": "fortiedr_triage.md",
    "compromise": "fortiedr_triage.md",
    "compromised": "fortiedr_triage.md",
    "hash": "fortiedr_triage.md",
    "file_hash": "fortiedr_triage.md",
    # Investigation strategy
    "lateral": "lateral_thinking.md",
    "lateral_thinking": "lateral_thinking.md",
    "stuck": "lateral_thinking.md",
    "reframing": "lateral_thinking.md",
}


def _get_available_domains() -> List[str]:
    """Return list of available domain skill files (excluding base)."""
    if not SKILLS_DIR.exists():
        return []
    return [f.stem for f in sorted(SKILLS_DIR.glob("*.md")) if f.stem != "base_investigation"]


# ---------------------------------------------------------------------------
# Shared state accumulated across tool calls within a single run
# ---------------------------------------------------------------------------

class EngineerToolState:
    """Mutable state shared across all meta-tool calls in one run."""

    def __init__(self):
        self.client_context: Optional[ClientContext] = None
        self.topology_nodes: List[TopologyNode] = []
        self.topology_edges: List[TopologyEdge] = []
        self.evidence_refs: List[str] = []  # EvidenceSnapshot IDs
        self.executed_signatures: List[str] = []
        self.tool_call_count: int = 0
        self.findings: Optional[Dict[str, Any]] = None  # Set by submit_findings


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_engineer_tools(
    *,
    customer_id: str,
    run_id: str,
    ticket_id: str,
    max_tool_calls: int = 30,
) -> tuple:
    """Return (tools_list, shared_state) for the Engineer agent.

    ``shared_state`` lets the caller read accumulated evidence_refs,
    topology, and client_context after the ReAct loop finishes.
    """
    state = EngineerToolState()

    async def _ensure_client_context() -> ClientContext:
        """Load the tenant context into state if not already loaded.

        search_tool_catalog may run before query_client_db; pack scoping needs
        the inventory either way.
        """
        if state.client_context is not None:
            return state.client_context

        from src.core.context_store import ContextStore
        from src.core.database import async_session_factory

        async with async_session_factory() as session:
            store = ContextStore(session)
            context = await store.get_active_context(customer_id)

        if not context:
            context = ClientContext(
                customer_id=customer_id,
                version="v0.0",
                inventory=[],
                baselines=[],
                dependencies=[],
            )

        state.client_context = context
        return context

    # ------------------------------------------------------------------
    # Tool 1: query_client_db
    # ------------------------------------------------------------------
    @tool
    async def query_client_db(query: str) -> str:
        """Query the client database to understand the tenant's environment.

        Returns the full client context: inventory (devices/components),
        dependencies (topology), baselines, and known recent changes.
        Call this FIRST before any diagnostic tool execution.

        Args:
            query: Description of what you want to know about the client
                   (e.g. "what devices does this tenant have").
        """
        context = await _ensure_client_context()

        # Seed topology from inventory
        nodes, edges = seed_topology_from_context(context)
        state.topology_nodes = nodes
        state.topology_edges = edges

        # Build a readable summary for the agent
        parts = [f"# Client Context for {customer_id}"]
        parts.append(f"Version: {context.version}")

        if context.inventory:
            parts.append(f"\n## Inventory ({len(context.inventory)} components)")
            for c in context.inventory:
                meta_str = f" | metadata: {json.dumps(c.metadata)}" if c.metadata else ""
                vendor_str = f" | vendor: {c.vendor}" if c.vendor else ""
                parts.append(f"- **{c.ref}** (id={c.id}, role={c.role}{vendor_str}{meta_str})")
        else:
            parts.append("\n## Inventory\nNo components registered.")

        if context.dependencies:
            parts.append(f"\n## Dependencies ({len(context.dependencies)} relationships)")
            for d in context.dependencies:
                parts.append(f"- {d.source_id} --[{d.relation}]--> {d.target_id}")

        if context.baselines:
            parts.append(f"\n## Baselines ({len(context.baselines)} metrics)")
            for b in context.baselines:
                parts.append(f"- {b.component_id}.{b.metric}: normal = {b.normal_value}")

        if context.known_changes:
            parts.append(f"\n## Known Recent Changes ({len(context.known_changes)} entries)")
            for kc in context.known_changes:
                comp_str = f" (component: {kc.component_id})" if kc.component_id else ""
                parts.append(f"- [{kc.date}] {kc.description}{comp_str}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Tool 2: load_domain_skill
    # ------------------------------------------------------------------
    @tool
    async def load_domain_skill(domain: str) -> str:
        """Load the investigation methodology for a specific IT domain.

        Call this BEFORE starting deep investigation to get domain-specific
        reasoning frameworks, step-by-step investigation templates, and
        common pitfalls for the area you're investigating.

        Args:
            domain: The IT domain to load methodology for.
                    Examples: "networking", "routing", "firewall", "vpn",
                    "ipsec", "virtualization", "vcenter", "storage", "san",
                    "security", "nat", "bgp", "ospf", "dns", "dhcp",
                    "tool_catalog" (learn advanced search techniques),
                    "licensing" (FortiGate license/FortiGuard entitlement verification),
                    "logs" (historical log retrieval: web browsing, traffic, events),
                    "lateral_thinking" (re-framing techniques when the investigation stalls)
        """
        domain_lower = domain.lower().strip().replace(" ", "_").replace("-", "_")

        # Direct filename match
        direct_path = SKILLS_DIR / f"{domain_lower}.md"
        if direct_path.exists():
            content = direct_path.read_text(encoding="utf-8")
            logger.info(f"Engineer: Loaded domain skill '{domain_lower}' ({len(content)} chars)")
            return content

        # Keyword mapping
        if domain_lower in DOMAIN_SKILL_MAP:
            skill_file = SKILLS_DIR / DOMAIN_SKILL_MAP[domain_lower]
            if skill_file.exists():
                content = skill_file.read_text(encoding="utf-8")
                logger.info(f"Engineer: Loaded domain skill '{domain_lower}' -> {DOMAIN_SKILL_MAP[domain_lower]} ({len(content)} chars)")
                return content

        # Not found
        available = _get_available_domains()
        return (
            f"No specific skill found for domain '{domain}'. "
            f"Available domain skills: {', '.join(available) if available else 'none'}. "
            f"Proceed with the base investigation methodology already in your system prompt."
        )

    # ------------------------------------------------------------------
    # Tool 3: search_tool_catalog
    # ------------------------------------------------------------------
    @tool
    async def search_tool_catalog(query: str) -> str:
        """Search for available diagnostic tools by describing what you need.

        Returns tool names, descriptions, and parameter schemas so you can
        decide which tools to execute and with what arguments.

        Args:
            query: Natural language description of what you want to accomplish
                   (e.g. "list firewall interfaces", "check OSPF neighbors",
                   "get system status overview").
        """
        from src.core.pack_matching import derive_allowed_pack_keys
        from src.core.qdrant import vector_store
        from src.core.registry import CapabilityRegistry

        # Version-aware scoping: only surface appliance-pack tools matching the
        # tenant's managed devices (vendor/product + firmware version). Tools
        # without pack identity (generic) always pass; None -> unscoped.
        context = await _ensure_client_context()
        allowed_pack_keys = derive_allowed_pack_keys(
            context.inventory, CapabilityRegistry.get_gateway_packs()
        )
        if allowed_pack_keys:
            logger.info(
                f"Engineer: tool catalog search scoped to packs {allowed_pack_keys}"
            )

        results = await vector_store.search_tool_catalog(
            intent=query,
            customer_id=customer_id,
            limit=10,
            read_only=True,
            allowed_pack_keys=allowed_pack_keys,
        )

        if not results:
            return "No matching tools found. Try a different search query."

        parts = [f"# Tool Catalog Results ({len(results)} matches)\n"]
        if allowed_pack_keys:
            parts.insert(
                0, f"Scoped to appliance packs: {', '.join(allowed_pack_keys)}\n"
            )
        for r in results:
            tool_name = r.get("tool_name", "unknown")
            desc = r.get("description", "No description")
            schema = r.get("args_schema", {})
            vendor = r.get("vendor", "")
            categories = r.get("categories", [])

            parts.append(f"## {tool_name}")
            if vendor:
                parts.append(f"Vendor: {vendor}")
            if categories:
                parts.append(f"Categories: {', '.join(categories)}")
            parts.append(f"Description: {desc}")

            parts.extend(_render_param_lines(schema))
            parts.append("")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Tool 3: search_knowledge_base
    # ------------------------------------------------------------------
    @tool
    async def search_knowledge_base(query: str) -> str:
        """Search the knowledge base for documentation, best practices, and known issues.

        Use this when you need vendor-specific expertise, error code meanings,
        configuration guidance, or domain knowledge.

        Args:
            query: What you want to know (e.g. "FortiGate IPSec phase2 rekeying",
                   "OSPF neighbor stuck in Init state", "best practices HA failover").
        """
        from src.core.qdrant import vector_store

        results = await vector_store.search_knowledge_base(
            query=query,
            customer_id=customer_id,
            limit=5,
        )

        if not results:
            return "No relevant knowledge base articles found."

        parts = [f"# Knowledge Base Results ({len(results)} articles)\n"]
        for r in results:
            source = r.get("source", "unknown")
            content = r.get("page_content", "")
            parts.append(f"## Source: {source}")
            parts.append(content[:2000])
            parts.append("")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Tool 4: execute_tool
    # ------------------------------------------------------------------
    @tool
    async def execute_tool(tool_name: str, tool_params: str) -> str:
        """Execute a diagnostic tool against a device.

        This runs an MCP tool with read-only access. The tool must exist in
        the tool catalog. Results are automatically stored as evidence.

        Args:
            tool_name: Exact tool name from the tool catalog search results,
                       or an exact tool name provided by a loaded domain skill
                       (skill anchors are pre-verified in this catalog).
            tool_params: JSON string with ALL parameters from the tool's schema.
                         Include every required parameter shown in the catalog.
                         Example: '{"device": "fgt_casa", "vdom": "root"}'
        """
        from src.core.mcp_executor import execute_mcp_tool
        from src.core.evidence_store import EvidenceStore

        # Guardrail: max tool calls
        if state.tool_call_count >= max_tool_calls:
            return f"ERROR: Maximum tool execution limit ({max_tool_calls}) reached. Produce your findings with the evidence gathered so far."

        # Parse args
        try:
            parsed_args = json.loads(tool_params) if isinstance(tool_params, str) else tool_params
        except json.JSONDecodeError as e:
            return f"ERROR: Invalid JSON in tool_params: {e}"

        if not isinstance(parsed_args, dict):
            return f"ERROR: tool_params must be a JSON object, got {type(parsed_args).__name__}"

        # Dedup check — signature over the LLM's own arguments (pre-injection)
        sig_input = f"{tool_name}::{json.dumps(parsed_args, sort_keys=True)}"
        sig_hash = hashlib.sha256(sig_input.encode()).hexdigest()[:16]
        signature = f"{tool_name}::{sig_hash}"

        if signature in state.executed_signatures:
            return f"SKIPPED: Tool '{tool_name}' with these exact arguments was already executed. Use different arguments or a different tool."

        # Shared guardrail pipeline: safety filter -> tenant governance ->
        # registry resolution -> framework-side tenant injection -> execution.
        llm_args = dict(parsed_args)  # what the LLM asked for, pre-injection
        started_at = datetime.utcnow()
        exec_result = await execute_mcp_tool(tool_name, parsed_args, customer_id)

        if not exec_result.ok:
            if exec_result.error_type == "safety":
                return f"ERROR: Tool '{tool_name}' blocked by safety policy. This tool or its arguments contain blocked keywords."
            if exec_result.preflight_failure and exec_result.error_type == "authorization":
                return f"ERROR: Tool '{tool_name}' is not allowed for this tenant."
            if exec_result.error_type == "not_found":
                return f"ERROR: Tool '{tool_name}' not found in registry. Search the tool catalog to find available tools."
            # Execution failure — agent handles errors via its own reasoning
            state.tool_call_count += 1
            await _audit_tool_call(
                run_id, customer_id, tool_name, llm_args,
                status="error", error=exec_result.error, started_at=started_at,
            )
            return f"ERROR executing {tool_name}: {exec_result.error}"

        result = exec_result.content
        parsed_args = exec_result.final_args  # args as dispatched (tenant injected)
        state.tool_call_count += 1
        state.executed_signatures.append(signature)

        # Store evidence
        evidence_store = EvidenceStore(
            customer_id=customer_id,
            run_id=run_id,
            ticket_id=ticket_id,
        )

        try:
            # Parse result for evidence storage
            content = result
            if isinstance(result, str):
                try:
                    content = json.loads(result)
                except (json.JSONDecodeError, TypeError):
                    pass

            snapshot = await evidence_store.save_evidence(
                tool_name=tool_name,
                tool_args=parsed_args,
                content=content,
            )
            state.evidence_refs.append(snapshot.id)
            evidence_id = snapshot.id
        except Exception as e:
            logger.error(f"Engineer: Failed to store evidence for {tool_name}: {e}")
            evidence_id = None

        await _audit_tool_call(
            run_id, customer_id, tool_name, llm_args,
            status="success", error=None, started_at=started_at,
            result_meta={
                "result_chars": len(str(result)) if result is not None else 0,
                "evidence_id": evidence_id,
            },
        )

        # Return result to agent
        if isinstance(result, (dict, list)):
            return json.dumps(result, indent=2, default=str)
        return str(result) if result else "Tool returned empty output."

    # ------------------------------------------------------------------
    # Tool 5: submit_findings
    # ------------------------------------------------------------------
    @tool
    async def submit_findings(
        summary: str,
        hypotheses: str,
        facts: str,
        plan: str,
        case_status: str,
    ) -> str:
        """Submit your final structured findings. Call this as your LAST action.

        You MUST call this tool exactly once, after completing your investigation,
        to deliver your findings in a structured format.

        Args:
            summary: Complete markdown report with all sections appropriate to
                     the ticket type (see Output Format guidance in system prompt).
            hypotheses: JSON array of hypotheses or key observations.
                        Each object: {"summary": "...", "confidence": 0.8,
                        "status": "verified|proposed|rejected",
                        "evidence_refs": ["ev_abc"], "rationale": "..."}
            facts: JSON array of facts discovered during investigation.
                   Each object: {"key": "...", "value": "...",
                   "source_evidence_id": "ev_abc", "confidence": 1.0}
            plan: JSON object with recommended actions.
                  {"diagnosis_steps": [...], "proposed_changes": [...],
                   "validation": [...], "rollback": [...]}
                  Each step: {"description": "...", "tool": "",
                  "expected_outcome": "", "risk": "low"}
            case_status: Final status — "resolved", "needs_human", or "blocked".
        """
        errors = []

        # Parse hypotheses
        try:
            parsed_hypotheses = json.loads(hypotheses) if isinstance(hypotheses, str) else hypotheses
            if not isinstance(parsed_hypotheses, list):
                parsed_hypotheses = []
                errors.append("hypotheses must be a JSON array")
        except (json.JSONDecodeError, TypeError):
            parsed_hypotheses = []
            errors.append("hypotheses JSON parse failed")

        # Parse facts
        try:
            parsed_facts = json.loads(facts) if isinstance(facts, str) else facts
            if not isinstance(parsed_facts, list):
                parsed_facts = []
                errors.append("facts must be a JSON array")
        except (json.JSONDecodeError, TypeError):
            parsed_facts = []
            errors.append("facts JSON parse failed")

        # Parse plan
        try:
            parsed_plan = json.loads(plan) if isinstance(plan, str) else plan
            if not isinstance(parsed_plan, dict):
                parsed_plan = {}
                errors.append("plan must be a JSON object")
        except (json.JSONDecodeError, TypeError):
            parsed_plan = {}
            errors.append("plan JSON parse failed")

        # Validate case_status
        valid_statuses = {"resolved", "needs_human", "blocked"}
        if case_status not in valid_statuses:
            case_status = "resolved"
            errors.append(f"case_status must be one of {valid_statuses}")

        state.findings = {
            "summary": summary,
            "hypotheses": parsed_hypotheses,
            "facts": parsed_facts,
            "plan": parsed_plan,
            "case_status": case_status,
            "evidence_refs": list(state.evidence_refs),
        }

        if errors:
            return f"Findings submitted with warnings: {'; '.join(errors)}. Findings stored."
        return "Findings submitted successfully."

    return [query_client_db, load_domain_skill, search_tool_catalog, search_knowledge_base, execute_tool, submit_findings], state
