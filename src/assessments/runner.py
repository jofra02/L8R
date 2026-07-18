"""AssessmentRunner: state machine + background job entry point.

State machine (transitions validated, committed per transition):

    draft -> queued -> collecting -> evaluating -> completed
                                                 | completed_with_errors
                                                 | failed
    queued|collecting|evaluating -> cancelled
    completed|completed_with_errors -> evaluating   (re-evaluate)

No crash recovery in the MVP: ``sweep_stale_runs`` marks runs left in an
active state (queued/collecting/evaluating) as failed at startup.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select, update

from src.assessments.evaluation.engine import evaluate_control
from src.assessments.reporting import build_report_model
from src.assessments.schema import AssessmentDefinitionModel
from src.assessments.scoring import compute_score, compute_stats

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("queued", "collecting", "evaluating")
TERMINAL_STATUSES = ("completed", "completed_with_errors", "failed", "cancelled")

_ALLOWED_TRANSITIONS: Dict[str, set] = {
    "draft": {"queued"},
    "queued": {"collecting", "cancelled", "failed"},
    "collecting": {"evaluating", "cancelled", "failed"},
    "evaluating": {"completed", "completed_with_errors", "cancelled", "failed"},
    "completed": {"evaluating"},
    "completed_with_errors": {"evaluating"},
}


class InvalidTransitionError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AssessmentRunner:
    """Executes one assessment run end to end (collection -> evaluation -> report)."""

    def __init__(self, run_id: str, customer_id: str):
        self.run_id = run_id
        self.customer_id = customer_id

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    async def transition(self, to_status: str, *, error: Optional[str] = None,
                         extra: Optional[Dict[str, Any]] = None) -> None:
        """Validated, individually-committed status transition."""
        from src.core.database import async_session_factory
        from src.core.orm import AssessmentRunORM
        async with async_session_factory() as session:
            run = (
                await session.execute(
                    select(AssessmentRunORM).where(
                        AssessmentRunORM.id == self.run_id,
                        AssessmentRunORM.customer_id == self.customer_id,
                    )
                )
            ).scalar_one_or_none()
            if run is None:
                raise InvalidTransitionError(f"run {self.run_id} not found")
            allowed = _ALLOWED_TRANSITIONS.get(run.status, set())
            if to_status not in allowed:
                raise InvalidTransitionError(
                    f"illegal transition {run.status} -> {to_status} for run {self.run_id}"
                )
            values: Dict[str, Any] = {"status": to_status}
            if error is not None:
                values["error"] = error
            if to_status == "collecting":
                values["started_at"] = _now()
            if to_status in TERMINAL_STATUSES:
                values["finished_at"] = _now()
            if extra:
                values.update(extra)
            await session.execute(
                update(AssessmentRunORM)
                .where(AssessmentRunORM.id == self.run_id)
                .values(**values)
            )
            await session.commit()
            logger.info(f"Assessment {self.run_id}: {run.status} -> {to_status}")

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    async def _load_run_bundle(self):
        from src.core.database import async_session_factory
        from src.core.orm import (
            AssessmentDefinitionVersionORM,
            AssessmentRunORM,
            AssessmentTargetORM,
        )
        async with async_session_factory() as session:
            run = (
                await session.execute(
                    select(AssessmentRunORM).where(
                        AssessmentRunORM.id == self.run_id,
                        AssessmentRunORM.customer_id == self.customer_id,
                    )
                )
            ).scalar_one_or_none()
            if run is None:
                raise RuntimeError(f"assessment run {self.run_id} not found")
            targets = (
                await session.execute(
                    select(AssessmentTargetORM).where(
                        AssessmentTargetORM.run_id == self.run_id
                    )
                )
            ).scalars().all()
            version = (
                await session.execute(
                    select(AssessmentDefinitionVersionORM).where(
                        AssessmentDefinitionVersionORM.id == run.definition_version_id
                    )
                )
            ).scalar_one_or_none()
            if version is None:
                raise RuntimeError(
                    f"definition version {run.definition_version_id} not found"
                )
            session.expunge_all()
        definition = AssessmentDefinitionModel.model_validate(version.content)
        return run, list(targets), definition, version.content

    async def _load_evidence_by_target(self) -> Dict[str, Dict[str, Any]]:
        """{target_id: {step_id: normalized}} for successful executions."""
        from src.core.database import async_session_factory
        from src.core.orm import AssessmentCollectionExecutionORM
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(AssessmentCollectionExecutionORM).where(
                        AssessmentCollectionExecutionORM.run_id == self.run_id,
                        AssessmentCollectionExecutionORM.status == "success",
                    )
                )
            ).scalars().all()
        evidence: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            if row.normalized is not None:
                evidence.setdefault(row.target_id, {})[row.step_id] = row.normalized
        return evidence

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------

    async def _evaluate(self, run, targets, definition: AssessmentDefinitionModel,
                        definition_content: Dict[str, Any]) -> str:
        """Evaluation + scoring + report. Returns the terminal status."""
        from src.core.database import async_session_factory
        from src.core.orm import (
            AssessmentControlResultORM,
            AssessmentReportORM,
            AssessmentRunORM,
        )

        evidence_by_target = await self._load_evidence_by_target()
        controls_total = len(definition.controls) * len(targets)
        controls_done = 0

        # Re-evaluation replaces prior results wholesale
        async with async_session_factory() as session:
            await session.execute(
                delete(AssessmentControlResultORM).where(
                    AssessmentControlResultORM.run_id == self.run_id
                )
            )
            await session.execute(
                delete(AssessmentReportORM).where(
                    AssessmentReportORM.run_id == self.run_id
                )
            )
            await session.commit()

        any_error = False
        result_rows: List[Dict[str, Any]] = []
        for target in targets:
            evidence = evidence_by_target.get(target.id, {})
            device_context = (
                f"device={target.device_name} vendor={definition.assessment.vendor} "
                f"product={definition.assessment.product}"
            )
            for control in definition.controls:
                evaluation = await evaluate_control(control, evidence, device_context)
                outcome = evaluation.outcome
                if outcome.status == "error":
                    any_error = True
                row = {
                    "target_id": target.id,
                    "control_id": control.id,
                    "severity": control.severity,
                    "category": control.category,
                    "status": outcome.status,
                }
                result_rows.append(row)
                async with async_session_factory() as session:
                    session.add(AssessmentControlResultORM(
                        id=str(uuid.uuid4()),
                        customer_id=self.customer_id,
                        run_id=self.run_id,
                        target_id=target.id,
                        control_id=control.id,
                        title=control.title,
                        category=control.category,
                        severity=control.severity,
                        status=outcome.status,
                        method=evaluation.method,
                        confidence=outcome.confidence,
                        explanation=outcome.explanation,
                        recommendation=outcome.recommendation
                            or (control.remediation.summary if control.remediation else None),
                        references=control.references,
                        evidence_refs=[
                            {"step_id": s} for s in outcome.evidence_refs
                        ],
                        llm_output=evaluation.llm_output,
                    ))
                    await session.commit()
                controls_done += 1
                if controls_done % 5 == 0 or controls_done == controls_total:
                    async with async_session_factory() as session:
                        await session.execute(
                            update(AssessmentRunORM)
                            .where(AssessmentRunORM.id == self.run_id)
                            .values(progress={
                                "phase": "evaluating",
                                "controls_total": controls_total,
                                "controls_done": controls_done,
                            })
                        )
                        await session.commit()

        score = compute_score(result_rows, definition.scoring)
        stats = compute_stats(result_rows)

        async with async_session_factory() as session:
            await session.execute(
                update(AssessmentRunORM)
                .where(AssessmentRunORM.id == self.run_id)
                .values(score=score, stats=stats)
            )
            await session.commit()

        # Build the report from fresh DB state
        run_fresh, targets_fresh, _, _ = await self._load_run_bundle()
        executions, results = await self._load_rows_for_report()
        model = build_report_model(run_fresh, targets_fresh, executions, results,
                                   definition_content)
        async with async_session_factory() as session:
            session.add(AssessmentReportORM(
                id=str(uuid.uuid4()),
                customer_id=self.customer_id,
                run_id=self.run_id,
                model=model,
            ))
            await session.commit()

        collection_ok = all(t.status == "collected" for t in targets_fresh)
        if any_error or not collection_ok:
            return "completed_with_errors"
        return "completed"

    async def _load_rows_for_report(self):
        from src.core.database import async_session_factory
        from src.core.orm import (
            AssessmentCollectionExecutionORM,
            AssessmentControlResultORM,
        )
        async with async_session_factory() as session:
            executions = (
                await session.execute(
                    select(AssessmentCollectionExecutionORM).where(
                        AssessmentCollectionExecutionORM.run_id == self.run_id
                    )
                )
            ).scalars().all()
            results = (
                await session.execute(
                    select(AssessmentControlResultORM).where(
                        AssessmentControlResultORM.run_id == self.run_id
                    )
                )
            ).scalars().all()
            session.expunge_all()
        return list(executions), list(results)

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    async def execute(self) -> None:
        """Full run: queued -> collecting -> evaluating -> terminal."""
        from src.assessments.collector import CollectionEngine
        from src.core.task_registry import task_registry

        try:
            run, targets, definition, content = await self._load_run_bundle()

            await self.transition("collecting")
            engine = CollectionEngine(self.run_id, self.customer_id, definition, targets)
            target_statuses = await engine.collect()

            if all(s == "failed" for s in target_statuses.values()):
                await self.transition(
                    "failed",
                    error="collection failed on every target",
                )
                return

            await self.transition("evaluating")
            run, targets, definition, content = await self._load_run_bundle()
            terminal = await self._evaluate(run, targets, definition, content)
            await self.transition(terminal)

        except asyncio.CancelledError:
            try:
                await self.transition("cancelled", error="cancelled by user")
            except Exception:  # noqa: BLE001 — already terminal/missing
                logger.warning(f"Assessment {self.run_id}: cancel transition skipped")
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(f"Assessment {self.run_id} failed")
            try:
                await self.transition("failed", error=str(e)[:2000])
            except Exception:  # noqa: BLE001
                logger.error(f"Assessment {self.run_id}: failed-transition skipped")
        finally:
            task_registry.unregister(self.run_id)

    async def reevaluate(self) -> None:
        """Re-run evaluation over existing evidence (completed* -> evaluating)."""
        from src.core.task_registry import task_registry
        try:
            await self.transition("evaluating")
            run, targets, definition, content = await self._load_run_bundle()
            terminal = await self._evaluate(run, targets, definition, content)
            await self.transition(terminal)
        except asyncio.CancelledError:
            try:
                await self.transition("cancelled", error="cancelled by user")
            except Exception:  # noqa: BLE001
                pass
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(f"Assessment {self.run_id} re-evaluation failed")
            try:
                await self.transition("failed", error=str(e)[:2000])
            except Exception:  # noqa: BLE001
                pass
        finally:
            task_registry.unregister(self.run_id)


async def sweep_stale_runs() -> int:
    """Startup reconciler: active runs from a previous process are failed.

    The task registry is in-memory, so any run still queued/collecting/
    evaluating at startup cannot be resumed in the MVP.
    """
    from src.core.database import async_session_factory
    from src.core.orm import AssessmentRunORM
    async with async_session_factory() as session:
        result = await session.execute(
            update(AssessmentRunORM)
            .where(AssessmentRunORM.status.in_(ACTIVE_STATUSES))
            .values(
                status="failed",
                error="interrupted by service restart",
                finished_at=_now(),
            )
        )
        await session.commit()
        count = result.rowcount or 0
    if count:
        logger.warning(f"Assessment sweep: {count} stale run(s) marked failed")
    return count
