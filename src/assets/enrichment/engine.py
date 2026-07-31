"""Deterministic asset enrichment engine.

Executes an enrichment pack (pinned snapshot version) against one managed
asset: sequential collection steps over execute_mcp_tool
(enforce_read_only=True, framework-injected tenant, device = asset.id — the
gateway registry is keyed by the asset id; ref/name are human reference
fields, never routing), then declarative mappings/subitems/relations. No LLM
anywhere.

State machine (assessments pattern): pending -> running -> completed |
completed_with_errors | failed, transitions validated and committed in
their own session. Background execution via asyncio.create_task +
task_registry; sweep_stale_sync_runs() reconciles orphans at startup.

Merge contract: manual data on the parent asset wins by default
(per-field provenance). Discovered sub-entities land in asset_subitems —
never in assets (assets are curated; discovery only provides visibility).
Subitems are upserted by (customer_id, parent, source, kind, external_id)
and marked absent when a complete (non-truncated) scan no longer returns
them — never deleted.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, update

from src.api.exceptions import APIError
from src.assessments.evaluation.sanitize import sanitize_payload
from src.assessments.normalizers import get_normalizer
from src.assets.enrichment import mappings as mp
from src.assets.registry import KIND_ENRICHMENT_PACK, get_pack_for_device_type
from src.assets.schema import EnrichmentPackDefinition, PackStep, SubitemsRule
from src.config import settings
from src.core import task_registry
from src.core.database import async_session_factory
from src.core.mcp_executor import execute_mcp_tool
from src.core.orm import (
    AssetAuditLogORM,
    AssetDefinitionVersionORM,
    AssetORM,
    AssetRelationORM,
    AssetSubitemORM,
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


async def _collect_step(step: PackStep, device_id: str, customer_id: str
                        ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Run one step (with optional pagination). Returns (evidence, error)."""
    base_args = {**step.params, "device": device_id}

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
    truncated = False
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
        truncated = True
        logger.warning(f"step '{step.id}': pagination cap "
                       f"({pg.max_pages} pages) reached — results truncated")
    return {"results": accumulated,
            "meta": {"pages": page - pg.start_page + 1, "truncated": truncated}}, None


async def _execute(run_id: str, customer_id: str) -> None:
    stats: Dict[str, Any] = {
        "steps_total": 0, "steps_failed": 0,
        "assets_updated": 0,
        "subitems_created": 0, "subitems_updated": 0, "subitems_absent": 0,
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
                asset_id = asset.id
                # Gateway devices are registered with id = asset.id
                # (service._gateway_payload); ref is a human slug and must
                # never be used for routing.
                device_id = asset_id
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
                data, error = await _collect_step(step, device_id, customer_id)
                if error is not None:
                    failures.append((step.id, error, step.required))
                    stats["steps_failed"] += 1
                    stats["warnings"].append(f"step '{step.id}': {error[:200]}")
                    continue
                if (data.get("meta") or {}).get("truncated"):
                    stats["warnings"].append(
                        f"step '{step.id}': pagination cap reached — results truncated")
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

        # Discovered sub-entities: land in asset_subitems, never in assets.
        # Rules run parents-before-children so nested rules can resolve
        # their parent row from this run's upserts.
        resolved: Dict[tuple, str] = {}  # (source, kind, external_id) -> row id
        for rule in _ordered_subitem_rules(pack.subitems):
            step_evidence = evidence.get(rule.step)
            if step_evidence is None:
                continue
            seen_by_parent: Dict[Optional[str], set] = {}
            for item in mp.extract_items(step_evidence, rule.items):
                parent_subitem_id: Optional[str] = None
                if rule.parent is not None:
                    parent_ext = mp.extract_path(item, rule.parent.external_id)
                    if parent_ext in (None, ""):
                        stats["warnings"].append(
                            f"subitems[{rule.step}]: item without parent identity skipped")
                        continue
                    parent_subitem_id = resolved.get(
                        (rule.identity.source, rule.parent.kind, str(parent_ext)))
                    if parent_subitem_id is None:
                        stats["warnings"].append(
                            f"subitems[{rule.step}]: parent "
                            f"{rule.parent.kind}/{parent_ext} not found in this "
                            "run; item skipped")
                        continue
                result = await _upsert_subitem(session, customer_id, asset, rule,
                                               item, run_id, stats, parent_subitem_id)
                if result is not None:
                    ext, row_id = result
                    seen_by_parent.setdefault(parent_subitem_id, set()).add(ext)
                    resolved[(rule.identity.source, rule.kind, ext)] = row_id
            if not (step_evidence.get("meta") or {}).get("truncated"):
                if rule.parent is None:
                    scope = {None: seen_by_parent.get(None, set())}
                else:
                    # Sweep only children of parents upserted this run: a
                    # parent the scan did not return keeps its children
                    # untouched; a returned parent with no children gets
                    # them all marked absent.
                    scope = {
                        rid: seen_by_parent.get(rid, set())
                        for (src, k, _e), rid in resolved.items()
                        if src == rule.identity.source and k == rule.parent.kind
                    }
                await _mark_absent_subitems(session, customer_id, asset.id,
                                            rule, scope, stats)

        # Discovered relations (match-only against existing assets).
        for rule in pack.relations:
            step_evidence = evidence.get(rule.step)
            if step_evidence is None:
                continue
            for item in mp.extract_items(step_evidence, rule.items):
                await _match_relation(session, customer_id, asset, rule, item, stats)

        await session.commit()


def _ordered_subitem_rules(rules: List[SubitemsRule]) -> List[SubitemsRule]:
    """Stable parents-before-children order. Pack validation guarantees the
    parent graph over kinds is a DAG, so the DFS terminates."""
    by_kind: Dict[tuple, List[SubitemsRule]] = {}
    for r in rules:
        by_kind.setdefault((r.identity.source, r.kind), []).append(r)
    ordered: List[SubitemsRule] = []
    done: set = set()

    def visit(rule: SubitemsRule) -> None:
        if id(rule) in done:
            return
        done.add(id(rule))
        if rule.parent is not None:
            for parent_rule in by_kind.get((rule.identity.source, rule.parent.kind), []):
                visit(parent_rule)
        ordered.append(rule)

    for r in rules:
        visit(r)
    return ordered


async def _upsert_subitem(session, customer_id: str, parent: AssetORM,
                          rule: SubitemsRule, item: Any, run_id: str,
                          stats: Dict[str, Any],
                          parent_subitem_id: Optional[str] = None,
                          ) -> Optional[tuple]:
    """Upsert one discovered sub-entity; returns (external_id, row_id), or
    None when the item carries no resolvable identity (skipped, warning).

    Direct assignment on purpose — no merge policy, no provenance: subitems
    are wholly source-owned. Human-curated data belongs on real assets.
    """
    external_id = mp.extract_path(item, rule.identity.external_id)
    if external_id in (None, ""):
        if rule.identity.fallback:
            external_id = mp.extract_path(item, rule.identity.fallback)
    if external_id in (None, ""):
        stats["warnings"].append(f"subitems[{rule.step}]: item without identity skipped")
        return None
    external_id = str(external_id)

    name = str(mp.extract_path(item, rule.name) or external_id)
    state = None
    if rule.state:
        raw_state = mp.extract_path(item, rule.state)
        if raw_state is not None:
            state = str(mp.apply_transform(raw_state, None, rule.state_map))
    attrs: Dict[str, Any] = {}
    for m in rule.attributes:
        value = mp.apply_transform(
            mp.extract_path(item, m.source), m.transform, m.value_map
        )
        if value is not None:
            attrs[m.target[len("attributes."):]] = value

    identity_scope = (
        AssetSubitemORM.parent_subitem_id.is_(None)
        if parent_subitem_id is None
        else AssetSubitemORM.parent_subitem_id == parent_subitem_id
    )
    row = (await session.execute(
        select(AssetSubitemORM).where(
            AssetSubitemORM.customer_id == customer_id,
            AssetSubitemORM.parent_asset_id == parent.id,
            identity_scope,
            AssetSubitemORM.source == rule.identity.source,
            AssetSubitemORM.kind == rule.kind,
            AssetSubitemORM.external_id == external_id,
        )
    )).scalars().first()

    now = _now()
    if row is None:
        row_id = uuid.uuid4().hex
        session.add(AssetSubitemORM(
            id=row_id, customer_id=customer_id,
            parent_asset_id=parent.id, parent_subitem_id=parent_subitem_id,
            source=rule.identity.source,
            kind=rule.kind, external_id=external_id, name=name, state=state,
            attributes=attrs, absent=False,
            first_seen_at=now, last_seen_at=now, last_sync_run_id=run_id,
        ))
        stats["subitems_created"] += 1
        return external_id, row_id
    if (row.name, row.state, row.attributes, row.absent) != (name, state, attrs, False):
        stats["subitems_updated"] += 1
    row.name = name
    row.state = state
    row.attributes = attrs
    row.absent = False
    row.last_seen_at = now
    row.last_sync_run_id = run_id
    return external_id, row.id


async def _mark_absent_subitems(session, customer_id: str, parent_id: str,
                                rule: SubitemsRule,
                                seen_by_parent: Dict[Optional[str], set],
                                stats: Dict[str, Any]) -> None:
    """Flag rows a complete scan no longer returned. Never deletes:
    retirement visibility is the point of the flag. An empty complete scan
    marking everything absent is the intended semantics.

    The sweep is scoped per hierarchy level: each key of `seen_by_parent`
    is one parent scope (None = root rows) and its value the external_ids
    seen there this run. Children of parents outside the map are never
    touched — external_ids are only unique within one parent."""
    for parent_subitem_id, seen in seen_by_parent.items():
        stmt = (
            update(AssetSubitemORM)
            .where(
                AssetSubitemORM.customer_id == customer_id,
                AssetSubitemORM.parent_asset_id == parent_id,
                AssetSubitemORM.parent_subitem_id.is_(None)
                if parent_subitem_id is None
                else AssetSubitemORM.parent_subitem_id == parent_subitem_id,
                AssetSubitemORM.source == rule.identity.source,
                AssetSubitemORM.kind == rule.kind,
                AssetSubitemORM.absent.is_(False),
            )
            .values(absent=True)
        )
        if seen:
            stmt = stmt.where(AssetSubitemORM.external_id.not_in(seen))
        result = await session.execute(stmt)
        stats["subitems_absent"] += result.rowcount or 0


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
