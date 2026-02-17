from typing import List, Dict, Any, Optional, Literal, TypedDict
from pydantic import BaseModel, Field
from datetime import datetime

# --- Enums & Literals ---
Severity = Literal["low", "medium", "high", "critical"]
TicketMode = Literal["incident", "change"]
ComponentRole = Literal["firewall", "router", "switch", "server", "process", "service", "unknown"]

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
    
    missing_info: List[str]
    hypotheses: List[Hypothesis]
    plan: Plan
    
    final_answer: str
    handoff: HandoffPackage
    
    # Meta information for flow control
    meta: Dict[str, Any]  # iterations, tool_calls, trace_id, cost
