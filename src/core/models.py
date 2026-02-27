from typing import List, Dict, Any, Optional, Literal, TypedDict
from pydantic import BaseModel, Field
from datetime import datetime

# --- Enums & Literals ---
Severity = Literal["low", "medium", "high", "critical"]
TicketMode = Literal["incident", "change"]
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
    mode: TicketMode
    text: str
    severity: Severity
    source: str  # e.g., "webhook:servicenow", "poller:api", "email"
    timestamps: Dict[str, str] = Field(default_factory=dict)
    raw_payload: Optional[Dict[str, Any]] = None

class Component(BaseModel):
    """A device, service, or entity involved in the issue."""
    id: str  # Unique identifier (e.g., hostname, IP, uuid)
    ref: str  # Human-readable reference name
    role: ComponentRole
    vendor: Optional[str] = None # e.g. "fortinet", "microsoft", "aws"
    priority: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ClientContext(BaseModel):
    """Context and constraints for a specific customer."""
    customer_id: str
    version: str
    inventory: List[Component] = Field(default_factory=list)
    dependencies: List[Dict[str, Any]] = Field(default_factory=list)
    baselines: List[Dict[str, Any]] = Field(default_factory=list)
    known_changes: List[Dict[str, Any]] = Field(default_factory=list)
    access_scopes: List[str] = Field(default_factory=list)

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

class Hypothesis(BaseModel):
    """A potential explanation or diagnosis."""
    id: str
    summary: str
    required_facts: List[str] = Field(default_factory=list)
    supporting_facts: List[str] = Field(default_factory=list)
    disconfirming_facts: List[str] = Field(default_factory=list)
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

# --- Global State (LangGraph) ---

class GlobalState(TypedDict):
    """The central state object passed between agents."""
    ticket: Ticket
    customer_id: str
    client_context: ClientContext
    
    classification: Classification
    components: List[Component]
    
    # Normalized facts extracted from evidence
    facts: Dict[str, Any]
    
    # References to raw evidence artifacts
    evidence_refs: List[EvidenceSnapshot]
    
    missing_info: List[str] # Legacy string list, keep for backward compat if needed
    pending_requirements: List[PendingRequirement] # Structured blocking requirements
    
    hypotheses: List[Hypothesis]
    scoring: ScoringResult  # Scoring/Decision Engine output
    plan: Plan
    
    # Topology / Dependency Graph
    topology_nodes: List[TopologyNode]
    topology_edges: List[TopologyEdge]
    path_analysis: PathAnalysis
    
    final_answer: str
    handoff: HandoffPackage
    
    # Meta information for flow control
    meta: Dict[str, Any]  # iterations, tool_calls, trace_id, cost
