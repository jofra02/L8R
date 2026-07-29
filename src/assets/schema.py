"""Pydantic schemas for asset-type and enrichment-pack YAML definitions.

Both definition kinds are authored as versioned YAML under
``src/assets/definitions/`` and snapshotted immutably into
``asset_definition_versions`` (same contract as the assessments registry).
Everything here is deterministic — the LLM plays no part in this module.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

FieldType = Literal[
    "string", "integer", "number", "boolean", "date", "datetime",
    "enum", "string_list", "ip", "json",
]

# Asset columns that dynamic attribute keys must not shadow.
RESERVED_FIELD_KEYS = frozenset({
    "id", "name", "ref", "type", "asset_type", "type_schema_version",
    "manufacturer", "model", "serial_number", "location", "owner",
    "ip_address", "fqdn", "status", "criticality", "tags",
    "purchase_date", "warranty_expires", "eol_date", "attributes",
    "provenance", "managed", "mcp_config", "sync_status", "sync_error",
    "last_synced_at", "external_source", "external_id", "customer_id",
    "created_at", "updated_at", "deleted_at", "created_by", "updated_by",
})

# Common columns an enrichment mapping may write directly.
MAPPABLE_COMMON_TARGETS = frozenset({
    "name", "manufacturer", "model", "serial_number", "location", "owner",
    "ip_address", "fqdn", "status", "criticality",
})

KNOWN_TRANSFORMS = frozenset({
    "to_datetime", "to_date", "lowercase", "first", "join",
})

_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


# --- Asset type definitions ---

class FieldValidation(BaseModel):
    pattern: Optional[str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    max_length: Optional[int] = None


class TypeFieldDef(BaseModel):
    key: str
    label: Optional[str] = None
    type: FieldType = "string"
    required: bool = False
    default: Optional[Any] = None
    enum: Optional[List[str]] = None
    filterable: bool = False
    searchable: bool = False
    sensitive: bool = False
    validation: Optional[FieldValidation] = None

    @model_validator(mode="after")
    def _check(self) -> "TypeFieldDef":
        if not _SNAKE_CASE.match(self.key):
            raise ValueError(f"field key '{self.key}' must be snake_case")
        if self.key in RESERVED_FIELD_KEYS:
            raise ValueError(f"field key '{self.key}' shadows a common asset column")
        if self.type == "enum" and not self.enum:
            raise ValueError(f"field '{self.key}': enum type requires enum values")
        if self.enum and self.type != "enum":
            raise ValueError(f"field '{self.key}': enum values only allowed on enum type")
        if self.required and self.default is None:
            # Versioning policy: a required field must carry a default so
            # assets written under older schema versions keep validating.
            raise ValueError(f"field '{self.key}': required fields must declare a default")
        if self.validation and self.validation.pattern:
            try:
                re.compile(self.validation.pattern)
            except re.error as e:
                raise ValueError(f"field '{self.key}': invalid pattern — {e}")
        return self


class AssetTypeRelations(BaseModel):
    allowed: List[str] = Field(default_factory=list)


class AssetTypeDefinition(BaseModel):
    type_id: str
    version: int = Field(..., ge=1)
    label: str
    category: str = ""
    # Legacy Component.role values that map onto this type (context adapter).
    roles: List[str] = Field(default_factory=list)
    # Open types (e.g. "generic") accept attribute keys not declared in fields.
    open_attributes: bool = False
    fields: List[TypeFieldDef] = Field(default_factory=list)
    relations: AssetTypeRelations = Field(default_factory=AssetTypeRelations)

    @model_validator(mode="after")
    def _check(self) -> "AssetTypeDefinition":
        if not _SNAKE_CASE.match(self.type_id):
            raise ValueError(f"type_id '{self.type_id}' must be snake_case")
        keys = [f.key for f in self.fields]
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            raise ValueError(f"type '{self.type_id}': duplicate field keys {sorted(dupes)}")
        return self

    def field_map(self) -> Dict[str, TypeFieldDef]:
        return {f.key: f for f in self.fields}


# --- Enrichment pack definitions ---

class PackPaginate(BaseModel):
    """Deterministic pagination loop over a list endpoint."""
    page_param: str
    size_param: str
    size: int = Field(default=100, ge=1)
    max_pages: int = Field(default=50, ge=1)
    start_page: int = 0


class PackStep(BaseModel):
    """Shape mirrors assessments CollectionStepDef + optional paginate."""
    id: str
    tool: str
    params: Dict[str, Any] = Field(default_factory=dict)
    required: bool = False
    depends_on: List[str] = Field(default_factory=list)
    normalizer: Optional[str] = None
    timeout_s: Optional[int] = None
    max_attempts: Optional[int] = None
    sanitize: List[str] = Field(default_factory=list)
    paginate: Optional[PackPaginate] = None


class FieldMapping(BaseModel):
    """Declarative copy from collected evidence to the asset model.

    source: dotted path into the step results (``<step_id>.<path>`` at pack
    level, or a path inside the item for `produces` mappings). Supports
    ``[N]`` list indices and ``[*]`` only within `items` selectors.
    target: a mappable common column or ``attributes.<key>``.
    """
    source: str
    target: str
    policy: Literal["manual_wins", "discovered_wins"] = "manual_wins"
    transform: Optional[str] = None
    value_map: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _check(self) -> "FieldMapping":
        if self.target not in MAPPABLE_COMMON_TARGETS and not self.target.startswith("attributes."):
            raise ValueError(
                f"mapping target '{self.target}' must be one of "
                f"{sorted(MAPPABLE_COMMON_TARGETS)} or attributes.<key>"
            )
        if self.transform and self.transform not in KNOWN_TRANSFORMS:
            raise ValueError(f"unknown transform '{self.transform}'")
        return self


class MatchSpec(BaseModel):
    path: str   # path inside the discovered item
    by: str     # asset field to match against: common column or attributes.<key>


class RelationRule(BaseModel):
    """Create relations by matching discovered items against EXISTING assets.

    v1 is match-only: no assets are created from relation rules.
    """
    step: str
    items: str = "[*]"
    type: str
    match: MatchSpec
    provenance: str = "discovered"


class ProducesIdentity(BaseModel):
    external_source: str
    external_id: str            # path inside the item
    fallback: Optional[str] = None  # fallback path when external_id is empty


class ProducesRelation(BaseModel):
    type: str = "managed_by"    # child -> parent relation


class ProducesRule(BaseModel):
    """Upsert child assets from a list step (e.g. FortiEDR collectors)."""
    step: str
    items: str = "[*]"
    asset_type: str
    identity: ProducesIdentity
    relation: Optional[ProducesRelation] = None
    mappings: List[FieldMapping] = Field(default_factory=list)


class PackCompatibility(BaseModel):
    device_types: List[str] = Field(default_factory=list)
    asset_types: List[str] = Field(default_factory=list)


class EnrichmentPackDefinition(BaseModel):
    pack_id: str
    version: int = Field(..., ge=1)
    label: str
    compatible: PackCompatibility
    steps: List[PackStep]
    mappings: List[FieldMapping] = Field(default_factory=list)
    relations: List[RelationRule] = Field(default_factory=list)
    produces: List[ProducesRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "EnrichmentPackDefinition":
        if not _SNAKE_CASE.match(self.pack_id):
            raise ValueError(f"pack_id '{self.pack_id}' must be snake_case")
        ids = [s.id for s in self.steps]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"pack '{self.pack_id}': duplicate step ids {sorted(dupes)}")
        known = set(ids)
        problems: List[str] = []
        for step in self.steps:
            for dep in step.depends_on:
                if dep == step.id:
                    problems.append(f"step '{step.id}' depends on itself")
                elif dep not in known:
                    problems.append(f"step '{step.id}': unknown dependency '{dep}'")
        for m in self.mappings:
            root = m.source.split(".", 1)[0].split("[", 1)[0]
            if root not in known:
                problems.append(f"mapping source '{m.source}': unknown step '{root}'")
        for r in self.relations:
            if r.step not in known:
                problems.append(f"relation rule: unknown step '{r.step}'")
        for p in self.produces:
            if p.step not in known:
                problems.append(f"produces rule: unknown step '{p.step}'")
        if problems:
            raise ValueError(f"pack '{self.pack_id}': " + "; ".join(problems))
        return self
