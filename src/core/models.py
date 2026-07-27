from typing import List, Dict, Any, Optional, Literal, TypedDict
from dataclasses import dataclass, field as dc_field
from pydantic import BaseModel, Field
from datetime import datetime

# --- Role Classification ---

EXECUTOR_ROLES = frozenset([
    "firewall", "router", "switch", "server", "host", "loadbalancer",
    "appliance", "controller", "gateway", "hypervisor", "node", "cluster",
    "database", "storage", "nas", "san",
])

TARGET_ROLES = frozenset([
    "subnet", "network", "ip", "address", "url", "service", "process",
    "endpoint", "user", "application", "container", "pod", "vm", "instance",
])


def is_executor_role(role: str) -> bool:
    """Return True if *role* (case-insensitive) matches an executor pattern."""
    return any(r in role.lower() for r in EXECUTOR_ROLES)


def is_target_role(role: str) -> bool:
    """Return True if *role* (case-insensitive) matches a target pattern."""
    return any(r in role.lower() for r in TARGET_ROLES)


# --- Enums & Literals ---
Severity = Literal["low", "medium", "high", "critical"]
TicketMode = Literal["incident", "change", "validation", "inquiry"]
CaseStatus = Literal[
    "new", "triaged", "modeled", "planned", "investigating",
    "synthesizing", "resolved", "blocked", "needs_human"
]
ComponentRole = Literal[
    # Network
    "firewall", "router", "switch", "loadbalancer", "gateway", "access_point",
    # Infrastructure
    "server", "host", "hypervisor", "node", "cluster", "storage", "nas", "san",
    # Cloud / Virtualization
    "vm", "container", "pod", "instance", "function",
    # Application
    "service", "process", "application", "database", "api", "queue",
    # Targets / Abstract
    "subnet", "network", "endpoint", "user", "dns_name", "url",
    # Generic
    "appliance", "controller", "unknown"
]

# --- Core Entities ---

class Ticket(BaseModel):
    """Normalized ticket input."""
    id: str
    external_id: Optional[str] = None  # ID in the source system (ITSM ticket number, etc.)
    mode: TicketMode
    text: str
    severity: Severity
    source: str  # e.g., "webhook:servicenow", "poller:api", "email"
    timestamps: Dict[str, str] = Field(default_factory=dict)
    raw_payload: Optional[Dict[str, Any]] = None

class Component(BaseModel):
    """A device, service, or entity involved in the issue."""
    id: str = Field(description="Exact asset ID from inventory when matched. For unknown assets use hostname or IP.")
    ref: str = Field(description="Human-readable reference name (e.g. hostname, display name)")
    role: ComponentRole
    vendor: Optional[str] = None # e.g. "fortinet", "microsoft", "aws"
    priority: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)

class InventoryDependency(BaseModel):
    """A known dependency/relationship between inventory components. Seeds the topology graph."""
    source_id: str                  # Component ID
    target_id: str                  # Component ID
    relation: str                   # "routes_to", "depends_on", "serves", "hosts", "connects_to"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class Baseline(BaseModel):
    """A known normal metric for a component — helps distinguish anomaly from expected state."""
    component_id: str               # Which component
    metric: str                     # "cpu_usage", "latency_ms", "session_count", "uptime_days"
    normal_value: str               # "< 60%", "~30ms", "> 99.9%"
    description: str = ""

class KnownChange(BaseModel):
    """A recent change in the environment — common root cause candidate."""
    date: str                       # "2026-02-25"
    description: str                # "Upgraded firmware on fgt_druidics to 7.4.5"
    component_id: Optional[str] = None  # Affected component
    change_type: str = "update"     # "update", "addition", "removal", "config_change"

class ClientContext(BaseModel):
    """Context and constraints for a specific customer."""
    customer_id: str
    version: str
    inventory: List[Component] = Field(default_factory=list)
    dependencies: List[InventoryDependency] = Field(default_factory=list)
    baselines: List[Baseline] = Field(default_factory=list)
    known_changes: List[KnownChange] = Field(default_factory=list)

# --- Reasoning & Artifacts ---

class ToolKnowledge(BaseModel):
    """Learned insight about successful tool usage."""
    tool_name: str
    vendor: str = "unknown"
    scenario: str = "general" # e.g. "checking interface status"
    error_pattern: Optional[str] = None # e.g. "AttributeError: ..."
    insight: str # The learned rule
    good_example: Dict[str, Any] # working args
    success_count: int = 1
    last_updated: datetime = Field(default_factory=datetime.now)

class ResolvedTicket(BaseModel):
    """A historically resolved case for index/retrieval (RAG)."""
    ticket_id: str
    problem_summary: str # Vectorized field
    resolution_summary: str
    root_cause: str
    tools_used: List[Dict[str, Any]] # "Chain of Thought"
    steps_taken: List[str] # High level steps
    
    # Metadata for filtering
    vendor: Optional[str] = None
    component_role: Optional[str] = None
    customer_id: str
    
    # Weighting & Quality
    resolution_status: Literal["resolved", "workaround", "unresolved"] = "resolved"
    score: int = Field(default=10, description="Quality score 0-10")
    
    resolved_at: datetime = Field(default_factory=datetime.now)

class EvidenceSnapshot(BaseModel):
    """Immutable record of evidence collected via tools."""
    id: str
    tool_call_id: str
    tool_name: str
    tool_args: Dict[str, Any]
    timestamp: datetime
    content_hash: str
    summary: str
    # The actual content is stored in Evidence Store, referenced here.
    storage_ref: str

class Fact(BaseModel):
    """A structured fact extracted from evidence with provenance."""
    key: str
    value: Any
    source_evidence_id: str = Field(description="EvidenceSnapshot ID that produced this fact")
    confidence: float = Field(default=1.0, description="0.0-1.0 confidence in the extracted value")
    timestamp: datetime = Field(default_factory=datetime.now)

class OpenQuestion(BaseModel):
    """A structured question driving investigation."""
    id: str
    question: str = Field(description="The specific question to answer")
    why: str = Field(default="", description="Why answering this matters for the case")
    depends_on: List[str] = Field(default_factory=list, description="IDs of questions that must be answered first")
    done_when: str = Field(default="", description="Criteria that indicate this question is answered")
    status: str = Field(default="open", description="open, answered, blocked, irrelevant")
    answer: str = Field(default="", description="The answer once resolved")
    source_hypothesis_id: str = Field(default="", description="Hypothesis that motivated this question")

class FulfillmentGoal(BaseModel):
    """A structured goal for change/request ticket fulfillment."""
    id: str
    description: str = Field(description="What needs to be accomplished")
    preconditions: List[str] = Field(default_factory=list, description="What must be true before this goal can be pursued")
    validation_criteria: List[str] = Field(default_factory=list, description="How to verify goal completion")
    status: str = Field(default="pending", description="pending, in_progress, completed, blocked")
    sub_goals: List[str] = Field(default_factory=list, description="IDs of child goals")

class Hypothesis(BaseModel):
    """A potential explanation or diagnosis."""
    id: str
    summary: str
    required_facts: List[str] = Field(default_factory=list)
    supporting_facts: List[str] = Field(default_factory=list)
    disconfirming_facts: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list, description="EvidenceSnapshot IDs supporting/contradicting this hypothesis")
    confidence: float = 0.0
    rank: int = Field(default=0, description="Priority rank (1 is highest)")
    status: str = Field(default="proposed", description="proposed, verified, rejected")
    next_playbooks: List[str] = Field(default_factory=list)
    rationale: str = ""

class PlanStep(BaseModel):
    """A single step in the resolution plan."""
    step_id: str
    description: str
    tool: str
    args: Dict[str, Any]
    expected_outcome: str
    risk: str = "low"

class Plan(BaseModel):
    """The structured plan for resolution (without execution)."""
    diagnosis_steps: List[PlanStep] = Field(default_factory=list)
    proposed_changes: List[PlanStep] = Field(default_factory=list)
    validation: List[PlanStep] = Field(default_factory=list)
    rollback: List[PlanStep] = Field(default_factory=list)

class Classification(BaseModel):
    """Result of the content classification step."""
    domains: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    rationale: str = ""
    mode: TicketMode = "incident"
    mode_confidence: float = 0.0

class HandoffPackage(BaseModel):
    """Final output artifact for human consumption."""
    case_file_artifacts: List[str] = Field(default_factory=list)
    recommended_escalation: Optional[Dict[str, str]] = None

class PendingRequirement(BaseModel):
    """Information that the agent needs from the user to proceed."""
    key: str # unique key e.g. "ip_asset_fgt_01"
    description: str # "IP Address for asset:fgt_01"
    source_hint: str # "CMDB, Device"
    tool_name: str # "ping"
    component_id: str # "asset:fgt_01"

class ScoringResult(BaseModel):
    """Output of the Scoring/Decision Engine node."""
    risk_score: float = Field(default=0.0, description="Overall risk score 1-10 (severity × confidence × impact)")
    confidence: float = Field(default=0.0, description="0.0-1.0 evidence coverage vs required facts")
    evidence_coverage: float = Field(default=0.0, description="Fraction of required facts that have evidence")
    decision: Literal["proceed_to_plan", "needs_more_evidence", "escalate_to_human"] = "needs_more_evidence"
    rationale: str = ""
    missing_facts: List[str] = Field(default_factory=list, description="Facts still needed for confident diagnosis")

# --- Topology / Dependency Graph ---

class TopologyNode(BaseModel):
    """An entity in the dependency/topology graph."""
    id: str                                     # Matches Component.id or auto-generated
    node_type: str                              # "device", "interface", "subnet", "service", "host", "vm", "container", "dns_name", "vrf", "tunnel"
    label: str = ""                             # Human-readable label
    metadata: Dict[str, Any] = Field(default_factory=dict)
    evidence_ref: Optional[str] = None          # EvidenceSnapshot ID that discovered this node

class TopologyEdge(BaseModel):
    """A relationship between two topology nodes that enables (or blocks) a flow."""
    source_id: str                              # Node ID
    target_id: str                              # Node ID
    relation: str                               # "routes_to", "policy_allow", "policy_deny", "nat",
                                                # "overlay", "dns_resolves", "depends_on", "serves",
                                                # "hosts", "proxies", "connects_to"
    direction: str = "uni"                      # "uni" | "bi"
    metadata: Dict[str, Any] = Field(default_factory=dict)  # domain-specific attrs
    confidence: float = 0.5                     # 0.0-1.0 (tool output = high, inferred = low)
    evidence_ref: Optional[str] = None          # EvidenceSnapshot ID or "inferred"

class PathConstraint(BaseModel):
    """A condition that must hold for a path to be viable."""
    constraint_type: str                        # "forward_route", "return_route", "policy_match",
                                                # "nat_correctness", "tls_valid", "auth_required",
                                                # "service_healthy", "dns_resolution"
    description: str                            # Human-readable
    status: str = "unknown"                     # "passed", "failed", "unknown"
    edge_ref: Optional[str] = None              # Related edge (source_id-target_id)
    evidence_ref: Optional[str] = None          # EvidenceSnapshot that confirmed/denied

class CandidatePath(BaseModel):
    """A plausible flow path between source and destination."""
    path_id: str
    source: str                                 # Origin node ID
    destination: str                            # Destination node ID
    hops: List[str] = Field(default_factory=list)  # Ordered edge keys ("src->dst")
    constraints: List[PathConstraint] = Field(default_factory=list)
    confidence: float = 0.0                     # Overall path viability
    status: str = "incomplete"                  # "viable", "blocked", "incomplete"
    evidence_refs: List[str] = Field(default_factory=list)

class PathAnalysis(BaseModel):
    """Output of the path synthesis and reachability evaluation."""
    candidate_paths: List[CandidatePath] = Field(default_factory=list)
    most_likely_breakpoints: List[Dict[str, Any]] = Field(default_factory=list)  # [{edge, constraint, reasoning}]
    missing_evidence: List[str] = Field(default_factory=list)
    suggested_probes: List[str] = Field(default_factory=list)  # Read-only intents to fill gaps

# --- Tool Selection Pipeline ---

class ToolIntent(BaseModel):
    """Short keyword query for semantic tool search."""
    query: str          # 2-6 word search query
    goal: str = ""      # What info this intent seeks (optional, for traceability)
    category: str = ""  # LLM-assigned IT domain category for cascading search

class ToolCandidate(BaseModel):
    """A tool retrieved by semantic search, awaiting LLM evaluation."""
    tool_name: str
    description: str
    args_schema: Dict[str, Any] = Field(default_factory=dict)
    search_score: float = 0.0
    source_intent: str = ""
    catalog_context: str = ""  # page_content from Qdrant: description + param summaries
    vendor: str = ""
    method: str = ""
    read_only: bool = True
    categories: List[str] = Field(default_factory=list)
    param_count: int = 0
    tier: int = 0  # 1=discovery/list, 2=specific/detail, 0=unclassified
    provides_identifiers: List[str] = Field(default_factory=list)
    requires_identifiers: List[str] = Field(default_factory=list)
    scope_params: List[str] = Field(default_factory=list)

class ToolEvaluation(BaseModel):
    """LLM judgment on a single candidate tool."""
    tool_name: str
    relevant: bool          # Does this tool help gather the needed info?
    reasoning: str          # Why or why not (1-2 sentences)
    priority: int = 0       # Relative priority (1=highest) among approved tools

class ToolSelection(BaseModel):
    """Approved tool with bound arguments, ready for execution."""
    name: str
    args: Dict[str, Any]
    evaluation: ToolEvaluation
    missing_params: Dict[str, str] = Field(
        default_factory=dict,
        description="Mandatory params not bound from context. key=param, value=description from schema"
    )
    requires_identifiers: List[str] = Field(default_factory=list)
    tier: int = 0


@dataclass
class ToolSelectionContext:
    """All context needed for tool selection decisions."""
    ticket_text: str
    component: Optional[Component] = None
    components: List[Component] = dc_field(default_factory=list)
    hypothesis: Optional[Hypothesis] = None       # For investigator mode
    facts: Dict[str, Any] = dc_field(default_factory=dict)
    path_context: str = ""
    evidence_summaries: str = ""
    mode: str = "evidence"  # "evidence" | "investigation" | "relational"
    # Relational mode fields
    source_component: Optional[Component] = None   # For relational mode
    target_component: Optional[Component] = None   # For relational mode


# --- Global State (LangGraph) ---

class GlobalState(TypedDict):
    """The central state object passed between agents."""
    ticket: Ticket
    customer_id: str
    client_context: ClientContext

    # Case lifecycle
    case_status: CaseStatus

    classification: Classification
    components: List[Component]

    # Normalized facts extracted from evidence
    facts: Dict[str, Any]
    # Structured facts with provenance (augments flat facts dict)
    structured_facts: List[Fact]

    # References to raw evidence artifacts
    evidence_refs: List[EvidenceSnapshot]

    missing_info: List[str] # Legacy string list, keep for backward compat if needed
    pending_requirements: List[PendingRequirement] # Structured blocking requirements

    # Investigation planning
    open_questions: List[OpenQuestion]

    hypotheses: List[Hypothesis]
    scoring: ScoringResult  # Scoring/Decision Engine output
    plan: Plan

    # Fulfillment (change/request tickets)
    fulfillment_goals: List[FulfillmentGoal]

    # Topology / Dependency Graph
    topology_nodes: List[TopologyNode]
    topology_edges: List[TopologyEdge]
    path_analysis: PathAnalysis

    final_answer: str
    handoff: HandoffPackage

    # Dedup: "tool_name::args_hash" strings executed in this run
    _executed_tool_signatures: List[str]

    # Meta information for flow control
    meta: Dict[str, Any]  # iterations, tool_calls, trace_id, cost
