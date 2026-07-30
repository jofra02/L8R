"""Deterministic asset enrichment engine.

Executes an enrichment pack (pinned snapshot version) against one managed
asset: sequential collection steps over execute_mcp_tool
(enforce_read_only=True, framework-injected tenant, device = asset.ref),
then declarative mappings/produces/relations. No LLM anywhere.

State machine (assessments pattern): pending -> running -> completed |
completed_with_errors | failed, transitions validated and committed in
their own session. Background execution via asyncio.create_task +
task_registry; sweep_stale_sync_runs() reconciles orphans at startup.

Merge contract: manual data wins by default (per-field provenance),
discovered children are upserted by (customer_id, external_source,
external_id) and never deleted when absent.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from src.api.exceptions import APIError
from src.assessments.evaluation.sanitize import sanitize_payload
from src.assessments.normalizers import get_normalizer
from src.assets.enrichment import mappings as mp
from src.assets.registry import KIND_ENRICHMENT_PACK, get_pack_for_device_type
from src.assets.schema import EnrichmentPackDefinition, PackStep
from src.config import settings
from src.core import task_registry
from src.core.database import async_session_factory
from src.core.mcp_executor import execute_mcp_tool
from src.core.orm import (
    AssetAuditLogORM,
    AssetDefinitionVersionORM,
    AssetORM,
    AssetRelationORM,
    AssetSyncRunORM,
)

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("pending", "running")
TERMINAL_STATUSES = ("completed", "completed_with_errors", "failed")

_ALLOWED_TRANSITIONS = {
    "pending": {"running", "failed"},
    "running": {"completed", "completed_with_errors", "failed"},
}

_RETRYABLE = {"connection", "timeout"}
_ACTOR = "system:enrichment"

_semaphore: Optional[asyncio.Semaphore] = None


class InvalidSyncTransitionError(ValueError):
    pass


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.ASSETS_SYNC_CONCURRENCY)
    return _semaphore


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def enqueue_enrichment(customer_id: str, asset_id: str, *, trigger: str) -> str:
    """Validate preconditions, persist a pending run and spawn the worker.

    Raises APIError(409 invalid_state) when a run is already active,
    APIError(422) when the asset is not managed or no compatible pack exists.
    """
    async with async_session_factory() as session:
        asset = (await session.execute(
            select(AssetORM).where(AssetORM.customer_id == customer_id,
                                   AssetORM.id == asset_id,
                                   AssetORM.deleted_at.is_(None))
        )).scalar_one_or_none()
        if asset is None:
            raise APIError(404, "not_found", f"Asset '{asset_id}' not found")
        if not asset.managed or not asset.mcp_config:
            raise APIError(422, "invalid_state",
                           "Asset is not MCP-managed; configure mcp_connection first")
        device_type = asset.mcp_config.get("device_type")
        pack = await get_pack_for_device_type(session, device_type)
        if pack is None:
            raise APIError(422, "invalid_state",
                           f"No enrichment pack for device_type '{device_type}'")

        active = (await session.execute(
            select(AssetSyncRunORM.id).where(
                AssetSyncRunORM.customer_id == customer_id,
                AssetSyncRunORM.asset_id == asset_id,
                AssetSyncRunORM.status.in_(ACTIVE_STATUSES),
            )
        )).first()
        if active is not None:
            raise APIError(409, "invalid_state",
                           f"An enrichment run is already active for asset '{asset_id}'")

        run = AssetSyncRunORM(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            asset_id=asset_id,
            pack_id=pack.pack_id,
            pack_version=pack.version,
            status="pending",
            trigger=trigger,
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    task = asyncio.create_task(_execute(run_id, customer_id))
    task_registry.register(f"asset-sync:{run_id}", task)
    logger.info(f"Enrichment run {run_id} queued for asset {asset_id} ({trigger})")
    return run_id


async def _transition(run_id: str, customer_id: str, to_status: str, *,
                      error: Optional[str] = None,
                      stats: Optional[Dict[str, Any]] = None) -> None:
    async with async_session_factory() as session:
        run = (await session.execute(
            select(AssetSyncRunORM).where(AssetSyncRunORM.id == run_id,
                                          AssetSyncRunORM.customer_id == customer_id)
        )).scalar_one_or_none()
        if run is None:
            raise InvalidSyncTransitionError(f"run {run_id} not found")
        allowed = _ALLOWED_TRANSITIONS.get(run.status, set())
        if to_status not in allowed:
            raise InvalidSyncTransitionError(
                f"run {run_id}: {run.status} -> {to_status} not allowed"
            )
        run.status = to_status
        if to_status == "running":
            run.started_at = _now()
        if to_status in TERMINAL_STATUSES:
            run.finished_at = _now()
        if error is not None:
            run.error = error
        if stats is not None:
            run.stats = stats
        await session.commit()


async def _load_pack_snapshot(session, pack_id: str, version: int) -> EnrichmentPackDefinition:
    row = (await session.execute(
        select(AssetDefinitionVersionORM).where(
            AssetDefinitionVersionORM.kind == KIND_ENRICHMENT_PACK,
            AssetDefinitionVersionORM.definition_id == pack_id,
            AssetDefinitionVersionORM.version == version,
        )
    )).scalar_one_or_none()
    if row is None:
        raise RuntimeError(f"pack snapshot {pack_id}@{version} not found")
    return EnrichmentPackDefinition.model_validate(row.content)


def _step_order(steps: List[PackStep]) -> List[PackStep]:
    """Dependency-respecting order (steps are validated acyclic-ish at load;
    a cycle degrades to file order)."""
    ordered: List[PackStep] = []
    done: set = set()
    remaining = list(steps)
    while remaining:
        progressed = False
        for step in list(remaining):
            if all(d in done for d in step.depends_on):
                ordered.append(step)
                done.add(step.id)
                remaining.remove(step)
                progressed = True
        if not progressed:  # cycle fallback
            ordered.extend(remaining)
            break
    return ordered


async def _call_tool(step: PackStep, args: Dict[str, Any], customer_id: str):
    timeout = step.timeout_s or settings.ASSETS_SYNC_STEP_TIMEOUT_S
    attempts = step.max_attempts or settings.ASSETS_SYNC_STEP_MAX_ATTEMPTS
    last = None
    for attempt in range(1, attempts + 1):
        result = await execute_mcp_tool(
            step.tool, args, customer_id,
            enforce_read_only=True, timeout_s=timeout,
        )
        last = result
        if result.ok and not result.gateway_error:
            return result
        if not (result.error_type in _RETRYABLE and attempt < attempts):
            return result
        await asyncio.sleep(2 ** (attempt - 1) + random.uniform(0, 0.5))
    return last


def _normalize(step: PackStep, content: Any) -> Dict[str, Any]:
    if step.sanitize:
        content, _truncated, _size = sanitize_payload(
            content, step.sanitize, settings.ASSESSMENT_MAX_EVIDENCE_BYTES
        )
    normalizer = get_normalizer(step.normalizer) if step.normalizer else get_normalizer("passthrough")
    return normalizer(content)


async def _collect_step(step: PackStep, asset_ref: str, customer_id: str
                        ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Run one step (with optional pagination). Returns (evidence, error)."""
    base_args = {**step.params, "device": asset_ref}

    if step.paginate is None:
        result = await _call_tool(step, base_args, customer_id)
        if result is None or not result.ok:
            return None, (result.error if result else "no result")
        if result.gateway_error:
            return None, str(result.content)[:500]
        return _normalize(step, result.content), None

    # Deterministic pagination loop.
    pg = step.paginate
    accumulated: List[Any] = []
    page = pg.start_page
    for _ in range(pg.max_pages):
        args = {**base_args, pg.page_param: page, pg.size_param: pg.size}
        result = await _call_tool(step, args, customer_id)
        if result is None or not result.ok:
            return None, (result.error if result else "no result")
        if result.gateway_error:
            return None, str(result.content)[:500]
        normalized = _normalize(step, result.content)
        items = normalized.get("results")
        if not isinstance(items, list):
            items = [items] if items else []
        accumulated.extend(items)
        if len(items) < pg.size:
            break
        page += 1
    else:
        logger.warning(f"step '{step.id}': pagination cap "
                       f"({pg.max_pages} pages) reached — results truncated")
    return {"results": accumulated, "meta": {"pages": page - pg.start_page + 1}}, None


async def _execute(run_id: str, customer_id: str) -> None:
    stats: Dict[str, Any] = {
        "steps_total": 0, "steps_failed": 0,
        "assets_created": 0, "assets_updated": 0,
        "relations_created": 0, "warnings": [],
    }
    try:
        async with _sem():
            await _transition(run_id, customer_id, "running")

            # Phase A: read asset + pinned pack snapshot (short session,
            # closed before any network I/O).
            async with async_session_factory() as session:
                run = (await session.execute(
                    select(AssetSyncRunORM).where(AssetSyncRunORM.id == run_id)
                )).scalar_one()
                asset = (await session.execute(
                    select(AssetORM).where(AssetORM.id == run.asset_id)
                )).scalar_one()
                pack = await _load_pack_snapshot(session, run.pack_id, run.pack_version)
                asset_ref = asset.ref
                asset_id = asset.id
                if pack.compatible.asset_types and \
                        asset.asset_type not in pack.compatible.asset_types:
                    stats["warnings"].append(
                        f"asset_type '{asset.asset_type}' not declared compatible "
                        f"with pack '{pack.pack_id}'"
                    )

            # Collection (network I/O, no DB session held).
            evidence: Dict[str, Dict[str, Any]] = {}
            failures: List[Tuple[str, str, bool]] = []
            for step in _step_order(pack.steps):
                stats["steps_total"] += 1
                if any(f[0] == dep for dep in step.depends_on for f in failures):
                    failures.append((step.id, "skipped: dependency failed", step.required))
                    stats["steps_failed"] += 1
                    continue
                data, error = await _collect_step(step, asset_ref, customer_id)
                if error is not None:
                    failures.append((step.id, error, step.required))
                    stats["steps_failed"] += 1
                    stats["warnings"].append(f"step '{step.id}': {error[:200]}")
                    continue
                evidence[step.id] = data

            if any(required for _, _, required in failures):
                detail = "; ".join(f"{sid}: {err[:200]}" for sid, err, req in failures if req)
                await _transition(run_id, customer_id, "failed",
                                  error=f"required step failed — {detail}", stats=stats)
                return

            # Phase B: apply mappings/produces/relations in one transaction.
            await _apply(run_id, customer_id, asset_id, pack, evidence, stats)

            status = "completed_with_errors" if (
                stats["steps_failed"] or stats["warnings"]
            ) else "completed"
            await _transition(run_id, customer_id, status, stats=stats)
    except asyncio.CancelledError:
        try:
            await _transition(run_id, customer_id, "failed", error="cancelled", stats=stats)
        except Exception:
            pass
        raise
    except Exception as e:
        logger.exception(f"Enrichment run {run_id} crashed")
        try:
            await _transition(run_id, customer_id, "failed", error=str(e)[:2000], stats=stats)
        except Exception:
            pass
    finally:
        task_registry.unregister(f"asset-sync:{run_id}")


async def _apply(run_id: str, customer_id: str, asset_id: str,
                 pack: EnrichmentPackDefinition,
                 evidence: Dict[str, Dict[str, Any]],
                 stats: Dict[str, Any]) -> None:
    async with async_session_factory() as session:
        asset = (await session.execute(
            select(AssetORM).where(AssetORM.customer_id == customer_id,
                                   AssetORM.id == asset_id)
        )).scalar_one_or_none()
        if asset is None or asset.deleted_at is not None:
            stats["warnings"].append("asset deleted during enrichment; results discarded")
            return

        # Self-enrichment.
        changed, fields = mp.apply_mappings(
            asset, pack.mappings, evidence, pack_id=pack.pack_id, run_id=run_id
        )
        if changed:
            stats["assets_updated"] += 1
            asset.updated_by = _ACTOR
        session.add(AssetAuditLogORM(
            customer_id=customer_id, asset_id=asset.id, actor=_ACTOR,
            action="enriched",
            changes={"fields": fields, "pack": f"{pack.pack_id}@{pack.version}"},
            sync_run_id=run_id,
        ))

        # Child assets (produces).
        for rule in pack.produces:
            step_evidence = evidence.get(rule.step)
            if step_evidence is None:
                continue
            for item in mp.extract_items(step_evidence, rule.items):
                await _upsert_child(session, customer_id, asset, pack, rule,
                                    item, run_id, stats)

        # Discovered relations (match-only against existing assets).
        for rule in pack.relations:
            step_evidence = evidence.get(rule.step)
            if step_evidence is None:
                continue
            for item in mp.extract_items(step_evidence, rule.items):
                await _match_relation(session, customer_id, asset, rule, item, stats)

        await session.commit()


async def _unique_ref(session, customer_id: str, base: str, own_id: str) -> str:
    ref = base
    for suffix in range(0, 50):
        candidate = ref if suffix == 0 else f"{base}-{suffix}"
        existing = (await session.execute(
            select(AssetORM.id).where(AssetORM.customer_id == customer_id,
                                      AssetORM.ref == candidate,
                                      AssetORM.deleted_at.is_(None),
                                      AssetORM.id != own_id)
        )).first()
        if existing is None:
            return candidate
    return f"{base}-{own_id[:8]}"


async def _upsert_child(session, customer_id: str, parent: AssetORM,
                        pack: EnrichmentPackDefinition, rule, item: Any,
                        run_id: str, stats: Dict[str, Any]) -> None:
    external_id = mp.extract_path(item, rule.identity.external_id)
    if external_id in (None, ""):
        if rule.identity.fallback:
            external_id = mp.extract_path(item, rule.identity.fallback)
    if external_id in (None, ""):
        stats["warnings"].append(f"produces[{rule.step}]: item without identity skipped")
        return
    external_id = str(external_id)

    child = (await session.execute(
        select(AssetORM).where(
            AssetORM.customer_id == customer_id,
            AssetORM.external_source == rule.identity.external_source,
            AssetORM.external_id == external_id,
        )
    )).scalars().first()

    if child is not None and child.deleted_at is not None:
        # Soft-deleted children are never resurrected by discovery.
        return

    if child is None:
        name = mp.extract_path(item, "name") or external_id
        child = AssetORM(
            id=uuid.uuid4().hex,
            customer_id=customer_id,
            name=str(name),
            ref="",  # set below
            asset_type=rule.asset_type,
            type_schema_version=1,
            external_source=rule.identity.external_source,
            external_id=external_id,
            attributes={},
            provenance={},
            created_by=_ACTOR,
            updated_by=_ACTOR,
        )
        child.ref = await _unique_ref(session, customer_id, str(name), child.id)
        session.add(child)
        changed, fields = mp.apply_mappings(
            child, rule.mappings, item, pack_id=pack.pack_id, run_id=run_id
        )
        stats["assets_created"] += 1
        # Flush the child before its audit row: the audit-log mapper can enter
        # the unit of work first (the parent's 'enriched' row is added before
        # any child exists), and its batched INSERT would then hit the
        # asset_audit_log.asset_id FK before the child row is inserted.
        await session.flush([child])
        session.add(AssetAuditLogORM(
            customer_id=customer_id, asset_id=child.id, actor=_ACTOR,
            action="created", changes={"fields": fields, "discovered_by": parent.id},
            sync_run_id=run_id,
        ))
    else:
        changed, fields = mp.apply_mappings(
            child, rule.mappings, item, pack_id=pack.pack_id, run_id=run_id
        )
        if changed:
            child.updated_by = _ACTOR
            stats["assets_updated"] += 1
            session.add(AssetAuditLogORM(
                customer_id=customer_id, asset_id=child.id, actor=_ACTOR,
                action="enriched", changes={"fields": fields},
                sync_run_id=run_id,
            ))

    if rule.relation is not None:
        await _ensure_relation(session, customer_id,
                               source_id=child.id, target_id=parent.id,
                               relation_type=rule.relation.type, stats=stats)


async def _ensure_relation(session, customer_id: str, *, source_id: str,
                           target_id: str, relation_type: str,
                           stats: Dict[str, Any],
                           details: Optional[Dict[str, Any]] = None) -> None:
    existing = (await session.execute(
        select(AssetRelationORM.id).where(
            AssetRelationORM.customer_id == customer_id,
            AssetRelationORM.source_asset_id == source_id,
            AssetRelationORM.target_asset_id == target_id,
            AssetRelationORM.relation_type == relation_type,
        )
    )).first()
    if existing is not None:
        return
    session.add(AssetRelationORM(
        customer_id=customer_id,
        source_asset_id=source_id,
        target_asset_id=target_id,
        relation_type=relation_type,
        provenance="discovered",
        details=details or {},
    ))
    stats["relations_created"] += 1


async def _match_relation(session, customer_id: str, parent: AssetORM,
                          rule, item: Any, stats: Dict[str, Any]) -> None:
    value = mp.extract_path(item, rule.match.path)
    if value in (None, ""):
        return
    by = rule.match.by
    stmt = select(AssetORM).where(AssetORM.customer_id == customer_id,
                                  AssetORM.deleted_at.is_(None),
                                  AssetORM.id != parent.id)
    if by.startswith("attributes."):
        stmt = stmt.where(AssetORM.attributes.contains({by[len("attributes."):]: value}))
    else:
        column = getattr(AssetORM, by, None)
        if column is None:
            return
        stmt = stmt.where(column == value)
    match = (await session.execute(stmt)).scalars().first()
    if match is None:
        return
    await _ensure_relation(session, customer_id,
                           source_id=parent.id, target_id=match.id,
                           relation_type=rule.type, stats=stats,
                           details={"matched_by": by, "value": str(value)})


async def sweep_stale_sync_runs() -> int:
    """Startup reconciler: in-memory tasks cannot survive a restart — every
    active run is failed."""
    count = 0
    try:
        async with async_session_factory() as session:
            runs = (await session.execute(
                select(AssetSyncRunORM).where(
                    AssetSyncRunORM.status.in_(ACTIVE_STATUSES)
                )
            )).scalars().all()
            for run in runs:
                run.status = "failed"
                run.finished_at = _now()
                run.error = "interrupted by service restart"
                count += 1
            await session.commit()
    except Exception as e:
        logger.error(f"sweep_stale_sync_runs failed: {e}")
    if count:
        logger.warning(f"Swept {count} stale asset sync runs to failed")
    return count
