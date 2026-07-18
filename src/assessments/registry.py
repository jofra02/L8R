"""DefinitionRegistry: load, validate and snapshot assessment definitions.

YAML files under ``src/assessments/definitions/`` are the authoring source.
On sync each file is parsed, schema-validated (including rule / parser /
normalizer name resolution) and upserted into
``assessment_definition_versions`` keyed by (definition_id, version) with a
canonical content hash.

Immutability contract: a file whose semantic content changed without a
version bump is REJECTED at sync time — historical runs always resolve the
exact snapshot they were executed with.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from sqlalchemy import select

from src.assessments import normalizers as normalizers_mod
from src.assessments.evaluation import rules as rules_mod
from src.assessments.schema import AssessmentDefinitionModel

logger = logging.getLogger(__name__)

DEFINITIONS_DIR = Path(__file__).parent / "definitions"


class DefinitionValidationError(ValueError):
    pass


class DefinitionImmutabilityError(ValueError):
    """Semantic content changed for an already-synced (definition_id, version)."""


def content_hash(model: AssessmentDefinitionModel) -> str:
    canonical = json.dumps(model.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_references(model: AssessmentDefinitionModel, source: str) -> None:
    """Fail fast on names that will not resolve at run time."""
    problems: List[str] = []
    known_norm = set(normalizers_mod.known_normalizers())
    for step in model.collection_steps:
        if step.normalizer and step.normalizer not in known_norm:
            problems.append(f"step '{step.id}': unknown normalizer '{step.normalizer}'")

    known_rules = set(rules_mod.known_rules())
    known_parsers = set(rules_mod.known_parsers())
    for control in model.controls:
        ev = control.evaluation
        if ev.rule and ev.rule not in known_rules:
            problems.append(f"control '{control.id}': unknown rule '{ev.rule}'")
        if ev.parser and ev.parser not in known_parsers:
            problems.append(f"control '{control.id}': unknown parser '{ev.parser}'")

    if problems:
        raise DefinitionValidationError(f"{source}: " + "; ".join(problems))


def load_definition_file(path: Path) -> AssessmentDefinitionModel:
    """Parse + fully validate one YAML definition file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise DefinitionValidationError(f"{path.name}: invalid YAML — {e}") from e
    try:
        model = AssessmentDefinitionModel.model_validate(raw)
    except Exception as e:
        raise DefinitionValidationError(f"{path.name}: schema validation failed — {e}") from e
    _validate_references(model, path.name)
    return model


def discover_definition_files(base_dir: Optional[Path] = None) -> List[Path]:
    base = base_dir or DEFINITIONS_DIR
    if not base.exists():
        return []
    return sorted(base.rglob("*.yaml"))


async def sync_definitions(session, base_dir: Optional[Path] = None) -> Dict[str, str]:
    """Upsert every valid definition file into the DB snapshot table.

    Returns {"<definition_id>@<version>": "created" | "unchanged"}.
    Raises DefinitionImmutabilityError when a synced version's content changed.
    """
    from src.core.orm import AssessmentDefinitionVersionORM

    outcome: Dict[str, str] = {}
    for path in discover_definition_files(base_dir):
        model = load_definition_file(path)
        meta = model.assessment
        digest = content_hash(model)
        key = f"{meta.id}@{meta.version}"

        existing = (
            await session.execute(
                select(AssessmentDefinitionVersionORM).where(
                    AssessmentDefinitionVersionORM.definition_id == meta.id,
                    AssessmentDefinitionVersionORM.version == meta.version,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            if existing.content_hash != digest:
                raise DefinitionImmutabilityError(
                    f"{key}: content changed without a version bump "
                    f"(db={existing.content_hash[:12]} file={digest[:12]}). "
                    f"Bump assessment.version instead of editing a published version."
                )
            outcome[key] = "unchanged"
            continue

        session.add(AssessmentDefinitionVersionORM(
            id=str(uuid.uuid4()),
            definition_id=meta.id,
            version=meta.version,
            vendor=meta.vendor,
            product=meta.product,
            name=meta.name,
            description=meta.description,
            content=model.model_dump(mode="json"),
            content_hash=digest,
        ))
        outcome[key] = "created"
        logger.info(f"Assessment definition synced: {key}")

    await session.commit()
    return outcome
