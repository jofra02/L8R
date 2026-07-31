"""Collection engine: deterministic evidence gathering for an assessment run.

Executes the definition's collection steps on every target through the shared
``execute_mcp_tool`` guardrail pipeline (read-only enforced), with:

- dependency-ordered execution (topological waves per target)
- global + per-device concurrency limits
- retry with exponential backoff + jitter for connection/timeout errors only
- idempotent re-entry (existing successful executions are skipped)
- in-run dedup of identical (tool, args, device) calls
- sanitization before persistence (secrets redacted, size-capped)
- raw evidence in the content-addressed EvidenceStore, normalized JSON in
  the execution row
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update

from src.assessments.normalizers import get_normalizer
from src.assessments.evaluation.sanitize import sanitize_payload
from src.assessments.schema import AssessmentDefinitionModel, CollectionStepDef
from src.config import settings
from src.core.mcp_executor import execute_mcp_tool

logger = logging.getLogger(__name__)

_RETRYABLE = {"connection", "timeout"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dedup_key(tool: str, args: Dict[str, Any], device: str) -> str:
    payload = f"{tool}::{json.dumps(args, sort_keys=True)}::{device}"
    return hashlib.sha256(payload.encode()).hexdigest()


def topo_waves(steps: List[CollectionStepDef]) -> List[List[CollectionStepDef]]:
    """Group steps into dependency waves (wave N only depends on waves < N)."""
    level: Dict[str, int] = {}
    by_id = {s.id: s for s in steps}

    def resolve(step_id: str, seen: tuple = ()) -> int:
        if step_id in level:
            return level[step_id]
        if step_id in seen:
            raise ValueError(f"dependency cycle at step '{step_id}'")
        step = by_id[step_id]
        lvl = 0 if not step.depends_on else 1 + max(
            resolve(d, (*seen, step_id)) for d in step.depends_on
        )
        level[step_id] = lvl
        return lvl

    for s in steps:
        resolve(s.id)
    waves: Dict[int, List[CollectionStepDef]] = {}
    for s in steps:
        waves.setdefault(level[s.id], []).append(s)
    return [waves[i] for i in sorted(waves)]


class CollectionEngine:
    """Collects evidence for one assessment run."""

    def __init__(
        self,
        run_id: str,
        customer_id: str,
        definition: AssessmentDefinitionModel,
        targets: List[Any],  # AssessmentTargetORM rows (detached ok: id/component_id/device_name)
    ):
        self.run_id = run_id
        self.customer_id = customer_id
        self.definition = definition
        self.targets = targets
        self._global_sem = asyncio.Semaphore(settings.ASSESSMENT_GLOBAL_CONCURRENCY)
        self._dedup: Dict[str, str] = {}  # dedup key -> execution id that ran it
        self._dedup_lock = asyncio.Lock()
        self._progress_lock = asyncio.Lock()
        self._steps_done = 0
        self._steps_failed = 0
        self._steps_total = len(self.definition.collection_steps) * len(targets)

    # ------------------------------------------------------------------
    # DB helpers (own short sessions, AuditService style)
    # ------------------------------------------------------------------

    async def _get_existing(self, target_id: str, step_id: str):
        from src.core.database import async_session_factory
        from src.core.orm import AssessmentCollectionExecutionORM
        async with async_session_factory() as session:
            return (
                await session.execute(
                    select(AssessmentCollectionExecutionORM).where(
                        AssessmentCollectionExecutionORM.run_id == self.run_id,
                        AssessmentCollectionExecutionORM.target_id == target_id,
                        AssessmentCollectionExecutionORM.step_id == step_id,
                    )
                )
            ).scalar_one_or_none()

    async def _upsert_execution(self, target_id: str, step: CollectionStepDef,
                                **fields) -> str:
        from src.core.database import async_session_factory
        from src.core.orm import AssessmentCollectionExecutionORM
        async with async_session_factory() as session:
            existing = (
                await session.execute(
                    select(AssessmentCollectionExecutionORM).where(
                        AssessmentCollectionExecutionORM.run_id == self.run_id,
                        AssessmentCollectionExecutionORM.target_id == target_id,
                        AssessmentCollectionExecutionORM.step_id == step.id,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                existing = AssessmentCollectionExecutionORM(
                    id=str(uuid.uuid4()),
                    customer_id=self.customer_id,
                    run_id=self.run_id,
                    target_id=target_id,
                    step_id=step.id,
                    tool_name=step.tool,
                )
                session.add(existing)
            for key, value in fields.items():
                setattr(existing, key, value)
            await session.commit()
            return existing.id

    async def _bump_progress(self, failed: bool) -> None:
        from src.core.database import async_session_factory
        from src.core.orm import AssessmentRunORM
        async with self._progress_lock:
            self._steps_done += 1
            if failed:
                self._steps_failed += 1
            progress = {
                "phase": "collecting",
                "steps_total": self._steps_total,
                "steps_done": self._steps_done,
                "steps_failed": self._steps_failed,
            }
        async with async_session_factory() as session:
            await session.execute(
                update(AssessmentRunORM)
                .where(AssessmentRunORM.id == self.run_id)
                .values(progress=progress)
            )
            await session.commit()

    async def _set_target_status(self, target_id: str, status: str,
                                 error: Optional[str] = None) -> None:
        from src.core.database import async_session_factory
        from src.core.orm import AssessmentTargetORM
        async with async_session_factory() as session:
            await session.execute(
                update(AssessmentTargetORM)
                .where(AssessmentTargetORM.id == target_id)
                .values(status=status, error=error)
            )
            await session.commit()

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    async def _execute_step(self, target, step: CollectionStepDef) -> bool:
        """Run one step on one target. Returns True on success."""
        existing = await self._get_existing(target.id, step.id)
        if existing is not None and existing.status == "success":
            # Idempotent re-entry (resume/retry): keep the prior evidence.
            async with self._progress_lock:
                self._steps_done += 1
            return True

        # Routing identity is the component/asset id — the gateway registry
        # is keyed by it; device_name is a human display label only.
        args = {**step.params, "device": target.component_id}
        key = _dedup_key(step.tool, args, target.component_id)
        async with self._dedup_lock:
            duplicate_of = self._dedup.get(key)
            if duplicate_of is None:
                self._dedup[key] = "pending"

        if duplicate_of is not None:
            # Identical call already made in this run — do not hit the device
            # again; record the reference.
            await self._upsert_execution(
                target.id, step,
                tool_args=args, status="skipped", error_type=None,
                error=f"duplicate of execution {duplicate_of}",
                finished_at=_now(),
            )
            await self._bump_progress(failed=False)
            return False

        max_attempts = step.max_attempts or settings.ASSESSMENT_STEP_MAX_ATTEMPTS
        timeout_s = step.timeout_s or settings.ASSESSMENT_STEP_TIMEOUT_S

        attempt = 0
        result = None
        while True:
            attempt += 1
            started = _now()
            exec_id = await self._upsert_execution(
                target.id, step,
                tool_args=args, status="running", attempt=attempt,
                started_at=started, error=None, error_type=None,
            )
            result = await execute_mcp_tool(
                step.tool, args, self.customer_id,
                enforce_read_only=True, timeout_s=timeout_s,
            )
            if result.ok and not result.gateway_error:
                break
            error_type = "device" if (result.ok and result.gateway_error) else result.error_type
            error_text = result.content if (result.ok and result.gateway_error) else result.error
            retryable = error_type in _RETRYABLE and attempt < max_attempts
            status = "timeout" if error_type == "timeout" else "failed"
            await self._upsert_execution(
                target.id, step,
                status="pending" if retryable else status,
                error_type=error_type, error=str(error_text)[:2000],
                finished_at=_now(), duration_ms=result.duration_ms,
            )
            if not retryable:
                async with self._dedup_lock:
                    self._dedup.pop(key, None)
                await self._bump_progress(failed=True)
                logger.warning(
                    f"Assessment {self.run_id}: step '{step.id}' failed on "
                    f"'{target.device_name}' ({error_type}): {str(error_text)[:200]}"
                )
                return False
            # Exponential backoff with jitter before the retry
            await asyncio.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.5))

        # Success path: sanitize -> store raw evidence -> normalize -> persist
        sanitized, truncated, size = sanitize_payload(
            result.content, step.sanitize, settings.ASSESSMENT_MAX_EVIDENCE_BYTES
        )

        raw_sha = None
        try:
            from src.core.evidence_store import EvidenceStore
            store = EvidenceStore(customer_id=self.customer_id, run_id=self.run_id)
            snapshot = await store.save_evidence(
                tool_name=step.tool, tool_args=args, content=sanitized,
                summary=f"assessment {self.run_id} step {step.id} on {target.device_name}",
            )
            raw_sha = snapshot.content_hash
        except Exception as e:  # noqa: BLE001 — evidence blob failure is not fatal
            logger.error(f"Assessment {self.run_id}: evidence store failed for "
                         f"step '{step.id}': {e}")

        normalized = None
        if step.normalizer:
            try:
                normalized = get_normalizer(step.normalizer)(sanitized)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Assessment {self.run_id}: normalizer "
                             f"'{step.normalizer}' failed on step '{step.id}': {e}")
                normalized = {"error": f"normalizer failed: {e}"}

        await self._upsert_execution(
            target.id, step,
            status="success", raw_evidence_sha=raw_sha,
            raw_size_bytes=size, truncated=truncated,
            normalized=normalized, normalizer=step.normalizer,
            finished_at=_now(), duration_ms=result.duration_ms,
        )
        async with self._dedup_lock:
            self._dedup[key] = exec_id
        await self._bump_progress(failed=False)
        return True

    async def _mark_skipped(self, target, step: CollectionStepDef, reason: str) -> None:
        await self._upsert_execution(
            target.id, step,
            tool_args={**step.params, "device": target.component_id},
            status="skipped", error=reason, finished_at=_now(),
        )
        await self._bump_progress(failed=False)

    async def _collect_target(self, target) -> str:
        """Collect all steps for one target. Returns the final target status."""
        device_sem = asyncio.Semaphore(settings.ASSESSMENT_DEVICE_CONCURRENCY)
        await self._set_target_status(target.id, "collecting")
        succeeded: set = set()
        failed: set = set()

        async def run_step(step: CollectionStepDef) -> None:
            failed_deps = [d for d in step.depends_on if d not in succeeded]
            if failed_deps:
                await self._mark_skipped(
                    target, step,
                    f"dependency failed/skipped: {', '.join(failed_deps)}",
                )
                failed.add(step.id)
                return
            async with self._global_sem, device_sem:
                ok = await self._execute_step(target, step)
            (succeeded if ok else failed).add(step.id)

        try:
            for wave in topo_waves(self.definition.collection_steps):
                await asyncio.gather(*(run_step(s) for s in wave))
        except asyncio.CancelledError:
            await self._cancel_pending(target.id)
            await self._set_target_status(target.id, "failed", "cancelled")
            raise

        required = {s.id for s in self.definition.collection_steps if s.required}
        missing_required = required - succeeded
        if not failed:
            status = "collected"
        elif succeeded and not missing_required:
            status = "partial"
        elif succeeded:
            status = "partial"
        else:
            status = "failed"
        error = (
            f"required steps failed: {', '.join(sorted(missing_required))}"
            if missing_required else None
        )
        await self._set_target_status(target.id, status, error)
        return status

    async def _cancel_pending(self, target_id: str) -> None:
        from src.core.database import async_session_factory
        from src.core.orm import AssessmentCollectionExecutionORM
        try:
            async with async_session_factory() as session:
                await session.execute(
                    update(AssessmentCollectionExecutionORM)
                    .where(
                        AssessmentCollectionExecutionORM.run_id == self.run_id,
                        AssessmentCollectionExecutionORM.target_id == target_id,
                        AssessmentCollectionExecutionORM.status.in_(["pending", "running"]),
                    )
                    .values(status="cancelled", finished_at=_now())
                )
                await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Assessment {self.run_id}: failed to mark cancelled rows: {e}")

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def collect(self) -> Dict[str, str]:
        """Collect all targets concurrently. Returns {target_id: final_status}."""
        statuses = await asyncio.gather(
            *(self._collect_target(t) for t in self.targets)
        )
        return {t.id: s for t, s in zip(self.targets, statuses)}
