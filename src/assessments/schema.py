"""Pydantic models for the assessment definition format.

Source of truth for validating the YAML files under
``src/assessments/definitions/``. Validation happens at registry sync time —
an invalid definition never reaches the database or a run.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Severity = Literal["critical", "high", "medium", "low"]
EvaluationType = Literal["rule", "parser", "llm", "hybrid"]

# Control outcomes (spec-mandated vocabulary)
CONTROL_STATUSES = (
    "pass", "fail", "warning", "not_applicable",
    "not_evaluated", "insufficient_evidence", "error",
)


class CollectionStepDef(BaseModel):
    """One deterministic collection step: which tool, which params, when."""

    id: str
    tool: str
    params: Dict[str, Any] = Field(default_factory=dict)
    required: bool = False
    depends_on: List[str] = Field(default_factory=list)
    normalizer: Optional[str] = None
    timeout_s: Optional[int] = None
    max_attempts: Optional[int] = None
    # Field names to redact from the collected payload before persistence
    sanitize: List[str] = Field(default_factory=list)

    @field_validator("id", "tool")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be non-empty")
        return v.strip()


class EvaluationSpec(BaseModel):
    type: EvaluationType
    rule: Optional[str] = None
    parser: Optional[str] = None
    llm_instructions: Optional[str] = None

    @model_validator(mode="after")
    def _check_refs(self) -> "EvaluationSpec":
        if self.type == "rule" and not self.rule:
            raise ValueError("evaluation.type=rule requires 'rule'")
        if self.type == "parser" and not self.parser:
            raise ValueError("evaluation.type=parser requires 'parser'")
        if self.type == "llm" and not self.llm_instructions:
            raise ValueError("evaluation.type=llm requires 'llm_instructions'")
        if self.type == "hybrid" and not (self.rule and self.llm_instructions):
            raise ValueError("evaluation.type=hybrid requires 'rule' and 'llm_instructions'")
        return self


class RemediationDef(BaseModel):
    summary: str


class ControlDef(BaseModel):
    id: str
    title: str
    category: str
    severity: Severity
    description: Optional[str] = None
    required_evidence: List[str] = Field(default_factory=list)
    optional_evidence: List[str] = Field(default_factory=list)
    evaluation: EvaluationSpec
    params: Dict[str, Any] = Field(default_factory=dict)
    expected_state: List[str] = Field(default_factory=list)
    references: List[str] = Field(default_factory=list)
    remediation: Optional[RemediationDef] = None


class ScoringConfig(BaseModel):
    version: str = "1.0"
    severity_weights: Dict[Severity, float] = Field(
        default_factory=lambda: {"critical": 10.0, "high": 5.0, "medium": 2.0, "low": 1.0}
    )
    status_credit: Dict[str, float] = Field(
        default_factory=lambda: {"pass": 1.0, "warning": 0.5, "fail": 0.0}
    )
    excluded_from_denominator: List[str] = Field(
        default_factory=lambda: [
            "not_applicable", "not_evaluated", "insufficient_evidence", "error",
        ]
    )


class AssessmentMeta(BaseModel):
    id: str
    version: str
    name: str
    vendor: str
    product: str
    description: Optional[str] = None
    min_product_version: Optional[str] = None


class AssessmentDefinitionModel(BaseModel):
    """Full parsed definition (the YAML root)."""

    assessment: AssessmentMeta
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    collection_steps: List[CollectionStepDef]
    controls: List[ControlDef]

    @model_validator(mode="after")
    def _cross_validate(self) -> "AssessmentDefinitionModel":
        step_ids = [s.id for s in self.collection_steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("duplicate collection step ids")

        control_ids = [c.id for c in self.controls]
        if len(control_ids) != len(set(control_ids)):
            raise ValueError("duplicate control ids")

        known = set(step_ids)
        for step in self.collection_steps:
            for dep in step.depends_on:
                if dep not in known:
                    raise ValueError(f"step '{step.id}' depends on unknown step '{dep}'")
                if dep == step.id:
                    raise ValueError(f"step '{step.id}' depends on itself")

        for control in self.controls:
            for ev in [*control.required_evidence, *control.optional_evidence]:
                if ev not in known:
                    raise ValueError(
                        f"control '{control.id}' references unknown evidence step '{ev}'"
                    )
        return self

    @property
    def categories(self) -> List[str]:
        seen: List[str] = []
        for c in self.controls:
            if c.category not in seen:
                seen.append(c.category)
        return seen
