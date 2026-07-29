"""Asset definition registry: load, validate and snapshot YAML definitions.

Two definition kinds share one immutable snapshot table
(``asset_definition_versions``):

- ``asset_type``     — ``definitions/types/*.yaml``  (AssetTypeDefinition)
- ``enrichment_pack``— ``definitions/packs/*.yaml``  (EnrichmentPackDefinition)

Immutability contract (same as src/assessments/registry.py): a file whose
semantic content changed without a version bump is rejected at sync time.
Pack validation fails fast on unknown normalizers and on tools that do not
pass the strict read-only name allowlist.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import yaml
from sqlalchemy import select

from src.assets.schema import AssetTypeDefinition, EnrichmentPackDefinition

logger = logging.getLogger(__name__)

DEFINITIONS_DIR = Path(__file__).parent / "definitions"
TYPES_DIR = DEFINITIONS_DIR / "types"
PACKS_DIR = DEFINITIONS_DIR / "packs"

KIND_ASSET_TYPE = "asset_type"
KIND_ENRICHMENT_PACK = "enrichment_pack"

DefinitionModel = Union[AssetTypeDefinition, EnrichmentPackDefinition]


class AssetDefinitionValidationError(ValueError):
    pass


class AssetDefinitionImmutabilityError(ValueError):
    """Semantic content changed for an already-synced (kind, id, version)."""


def content_hash(model: DefinitionModel) -> str:
    canonical = json.dumps(model.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_pack_references(model: EnrichmentPackDefinition, source: str) -> None:
    """Fail fast on names that will not resolve or execute at run time."""
    from src.assessments import normalizers as normalizers_mod
    from src.core.mcp_executor import is_read_only_tool_name

    problems: List[str] = []
    known_norm = set(normalizers_mod.known_normalizers())
    for step in model.steps:
        if step.normalizer and step.normalizer not in known_norm:
            problems.append(f"step '{step.id}': unknown normalizer '{step.normalizer}'")
        if not is_read_only_tool_name(step.tool):
            problems.append(f"step '{step.id}': tool '{step.tool}' fails the read-only allowlist")
    if problems:
        raise AssetDefinitionValidationError(f"{source}: " + "; ".join(problems))


def load_type_file(path: Path) -> AssetTypeDefinition:
    return _load_file(path, AssetTypeDefinition)


def load_pack_file(path: Path) -> EnrichmentPackDefinition:
    model = _load_file(path, EnrichmentPackDefinition)
    _validate_pack_references(model, path.name)
    return model


def _load_file(path: Path, model_cls):
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise AssetDefinitionValidationError(f"{path.name}: invalid YAML — {e}") from e
    try:
        return model_cls.model_validate(raw)
    except AssetDefinitionValidationError:
        raise
    except Exception as e:
        raise AssetDefinitionValidationError(f"{path.name}: schema validation failed — {e}") from e


def discover_files(base_dir: Optional[Path] = None) -> List[Tuple[str, Path]]:
    """Return (kind, path) pairs for every definition file."""
    base = base_dir or DEFINITIONS_DIR
    out: List[Tuple[str, Path]] = []
    types_dir = base / "types"
    packs_dir = base / "packs"
    if types_dir.exists():
        out.extend((KIND_ASSET_TYPE, p) for p in sorted(types_dir.glob("*.yaml")))
    if packs_dir.exists():
        out.extend((KIND_ENRICHMENT_PACK, p) for p in sorted(packs_dir.glob("*.yaml")))
    return out


async def sync_definitions(session, base_dir: Optional[Path] = None) -> Dict[str, str]:
    """Upsert every valid definition file into the DB snapshot table.

    Returns {"<kind>:<id>@<version>": "created" | "unchanged"}.
    Raises AssetDefinitionImmutabilityError on content drift for a synced version.
    """
    from src.core.orm import AssetDefinitionVersionORM

    outcome: Dict[str, str] = {}
    for kind, path in discover_files(base_dir):
        if kind == KIND_ASSET_TYPE:
            model = load_type_file(path)
            def_id, version, label = model.type_id, model.version, model.label
        else:
            model = load_pack_file(path)
            def_id, version, label = model.pack_id, model.version, model.label

        digest = content_hash(model)
        key = f"{kind}:{def_id}@{version}"

        existing = (
            await session.execute(
                select(AssetDefinitionVersionORM).where(
                    AssetDefinitionVersionORM.kind == kind,
                    AssetDefinitionVersionORM.definition_id == def_id,
                    AssetDefinitionVersionORM.version == version,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            if existing.content_hash != digest:
                raise AssetDefinitionImmutabilityError(
                    f"{key}: content changed without a version bump "
                    f"(db={existing.content_hash[:12]} file={digest[:12]}). "
                    f"Bump the definition version instead of editing a published one."
                )
            outcome[key] = "unchanged"
            continue

        session.add(AssetDefinitionVersionORM(
            id=str(uuid.uuid4()),
            kind=kind,
            definition_id=def_id,
            version=version,
            label=label,
            content=model.model_dump(mode="json"),
            content_hash=digest,
        ))
        outcome[key] = "created"
        logger.info(f"Asset definition synced: {key}")

    await session.commit()
    return outcome


# --- Runtime accessors (latest version per definition id) ---

async def _latest_by_kind(session, kind: str) -> Dict[str, dict]:
    from src.core.orm import AssetDefinitionVersionORM

    rows = (
        await session.execute(
            select(AssetDefinitionVersionORM)
            .where(AssetDefinitionVersionORM.kind == kind)
            .order_by(AssetDefinitionVersionORM.definition_id,
                      AssetDefinitionVersionORM.version)
        )
    ).scalars().all()
    latest: Dict[str, dict] = {}
    for row in rows:  # ordered ascending — the last one per id wins
        latest[row.definition_id] = row.content
    return latest


async def get_latest_types(session) -> Dict[str, AssetTypeDefinition]:
    raw = await _latest_by_kind(session, KIND_ASSET_TYPE)
    return {k: AssetTypeDefinition.model_validate(v) for k, v in raw.items()}


async def get_latest_type(session, type_id: str) -> Optional[AssetTypeDefinition]:
    types = await get_latest_types(session)
    return types.get(type_id)


async def get_latest_packs(session) -> Dict[str, EnrichmentPackDefinition]:
    raw = await _latest_by_kind(session, KIND_ENRICHMENT_PACK)
    return {k: EnrichmentPackDefinition.model_validate(v) for k, v in raw.items()}


async def get_pack_for_device_type(session, device_type: str) -> Optional[EnrichmentPackDefinition]:
    for pack in (await get_latest_packs(session)).values():
        if device_type in pack.compatible.device_types:
            return pack
    return None
