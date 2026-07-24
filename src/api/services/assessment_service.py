"""Service layer for the Device Assessment API.

Owns run lifecycle orchestration (create/start/cancel/reevaluate) and all
tenant-scoped queries. Background execution reuses the platform pattern:
``asyncio.create_task`` + ``src.core.task_registry`` keyed by run id.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.exceptions import APIError
from src.api.schemas.assessment import AssessmentCreate
from src.assessments.runner import ACTIVE_STATUSES, AssessmentRunner
from src.assessments.schema import AssessmentDefinitionModel
from src.config import settings
from src.core import task_registry
from src.core.context_store import ContextStore
from src.core.orm import (
    AssessmentCollectionExecutionORM,
    AssessmentControlResultORM,
    AssessmentDefinitionVersionORM,
    AssessmentReportORM,
    AssessmentRunORM,
    AssessmentTargetORM,
)

logger = logging.getLogger(__name__)


class AssessmentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Definitions
    # ------------------------------------------------------------------

    async def list_definitions(self) -> List[AssessmentDefinitionVersionORM]:
        rows = (
            await self.db.execute(
                select(AssessmentDefinitionVersionORM).order_by(
                    AssessmentDefinitionVersionORM.definition_id,
                    AssessmentDefinitionVersionORM.created_at.desc(),
                )
            )
        ).scalars().all()
        return list(rows)

    async def get_definition_version(
        self, definition_id: str, version: str
    ) -> AssessmentDefinitionVersionORM:
        row = (
            await self.db.execute(
                select(AssessmentDefinitionVersionORM).where(
                    AssessmentDefinitionVersionORM.definition_id == definition_id,
                    AssessmentDefinitionVersionORM.version == version,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, "not_found",
                           f"Assessment definition '{definition_id}' version "
                           f"'{version}' not found")
        return row

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    async def create_run(
        self, customer_id: str, body: AssessmentCreate, requested_by: Optional[str]
    ) -> Tuple[AssessmentRunORM, List[AssessmentTargetORM], List[str]]:
        version = await self.get_definition_version(
            body.definition_id, body.definition_version
        )
        definition = AssessmentDefinitionModel.model_validate(version.content)

        # Resolve targets from the tenant inventory (snapshot at creation time)
        context = await ContextStore(self.db).get_active_context(customer_id)
        components = {c.id: c for c in (context.inventory if context else [])}

        warnings: List[str] = []
        targets: List[AssessmentTargetORM] = []
        run_id = str(uuid.uuid4())
        for component_id in dict.fromkeys(body.component_ids):
            component = components.get(component_id)
            if component is None:
                raise APIError(422, "validation_error",
                               f"Component '{component_id}' not found in inventory")
            mcp = (component.metadata or {}).get("mcp") or {}
            if not mcp.get("managed"):
                raise APIError(422, "validation_error",
                               f"Component '{component.ref}' is not an MCP-managed device")
            if mcp.get("vendor") and mcp["vendor"] != definition.assessment.vendor:
                warnings.append(
                    f"Device '{component.ref}' vendor '{mcp['vendor']}' does not match "
                    f"definition vendor '{definition.assessment.vendor}'."
                )
            targets.append(AssessmentTargetORM(
                id=str(uuid.uuid4()),
                customer_id=customer_id,
                run_id=run_id,
                component_id=component.id,
                device_name=component.ref,
                device_meta={k: v for k, v in mcp.items() if k != "sync"},
            ))

        warnings.extend(self._preflight_tools(definition))

        run = AssessmentRunORM(
            id=run_id,
            customer_id=customer_id,
            definition_version_id=version.id,
            definition_id=version.definition_id,
            definition_version=version.version,
            name=body.name,
            status="draft",
            requested_by=requested_by,
            params=body.params,
            progress={"phase": "draft"},
        )
        self.db.add(run)
        for t in targets:
            self.db.add(t)
        await self.db.commit()
        return run, targets, warnings

    @staticmethod
    def _preflight_tools(definition: AssessmentDefinitionModel) -> List[str]:
        """Compatibility warnings for the wizard: tools missing from the
        registry or outside the read-only allowlist (never silent)."""
        from src.core.mcp_executor import is_read_only_tool_name
        from src.core.registry import CapabilityRegistry

        warnings: List[str] = []
        for step in definition.collection_steps:
            if not is_read_only_tool_name(step.tool):
                warnings.append(
                    f"Step '{step.id}': tool '{step.tool}' is outside the read-only "
                    f"allowlist and will be blocked."
                )
                continue
            try:
                if CapabilityRegistry.get_tool(step.tool) is None:
                    warnings.append(
                        f"Step '{step.id}': tool '{step.tool}' is not available in the "
                        f"tool registry; the step will fail unless the gateway exposes it."
                    )
            except Exception:  # noqa: BLE001 — registry not initialized (tests/CLI)
                break
        return warnings

    async def _get_run(self, customer_id: str, run_id: str) -> AssessmentRunORM:
        run = (
            await self.db.execute(
                select(AssessmentRunORM).where(
                    AssessmentRunORM.id == run_id,
                    AssessmentRunORM.customer_id == customer_id,
                )
            )
        ).scalar_one_or_none()
        if run is None:
            raise APIError(404, "not_found", f"Assessment '{run_id}' not found")
        return run

    async def start_run(self, customer_id: str, run_id: str) -> AssessmentRunORM:
        run = await self._get_run(customer_id, run_id)
        if run.status != "draft":
            raise APIError(409, "invalid_state",
                           f"Assessment is '{run.status}', only 'draft' can be started")

        runner = AssessmentRunner(run_id, customer_id)
        await runner.transition("queued")
        task = asyncio.create_task(runner.execute())
        task_registry.register(run_id, task)
        await self.db.refresh(run)
        return run

    async def cancel_run(self, customer_id: str, run_id: str) -> AssessmentRunORM:
        run = await self._get_run(customer_id, run_id)
        if run.status not in ACTIVE_STATUSES:
            raise APIError(409, "invalid_state",
                           f"Assessment is '{run.status}', nothing to cancel")
        if not task_registry.cancel(run_id):
            # Task not in this process (restart) — mark the row directly.
            runner = AssessmentRunner(run_id, customer_id)
            await runner.transition("cancelled", error="cancelled by user (no live task)")
        await self.db.refresh(run)
        return run

    async def reevaluate_run(self, customer_id: str, run_id: str) -> AssessmentRunORM:
        run = await self._get_run(customer_id, run_id)
        if run.status not in ("completed", "completed_with_errors"):
            raise APIError(409, "invalid_state",
                           f"Assessment is '{run.status}', only completed runs can be "
                           f"re-evaluated")
        if task_registry.is_running(run_id):
            raise APIError(409, "conflict", "Assessment already has a live task")
        runner = AssessmentRunner(run_id, customer_id)
        task = asyncio.create_task(runner.reevaluate())
        task_registry.register(run_id, task)
        return run

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_runs(
        self, customer_id: str, *, page: int, page_size: int,
        status: Optional[str] = None, definition_id: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[AssessmentRunORM], Dict[str, int], int, int]:
        base = select(AssessmentRunORM).where(
            AssessmentRunORM.customer_id == customer_id
        )
        if status:
            base = base.where(AssessmentRunORM.status == status)
        if definition_id:
            base = base.where(AssessmentRunORM.definition_id == definition_id)
        if search:
            base = base.where(AssessmentRunORM.name.ilike(f"%{search}%"))

        total = (
            await self.db.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()

        rows = (
            await self.db.execute(
                base.order_by(AssessmentRunORM.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        counts: Dict[str, int] = {}
        if rows:
            count_rows = (
                await self.db.execute(
                    select(
                        AssessmentTargetORM.run_id,
                        func.count(AssessmentTargetORM.id),
                    )
                    .where(AssessmentTargetORM.run_id.in_([r.id for r in rows]))
                    .group_by(AssessmentTargetORM.run_id)
                )
            ).all()
            counts = {run_id: count for run_id, count in count_rows}

        total_pages = max(1, math.ceil(total / page_size))
        return list(rows), counts, total, total_pages

    async def get_run_detail(
        self, customer_id: str, run_id: str
    ) -> Tuple[AssessmentRunORM, List[AssessmentTargetORM]]:
        run = await self._get_run(customer_id, run_id)
        targets = (
            await self.db.execute(
                select(AssessmentTargetORM).where(
                    AssessmentTargetORM.run_id == run_id
                )
            )
        ).scalars().all()
        return run, list(targets)

    async def list_executions(
        self, customer_id: str, run_id: str, *,
        target_id: Optional[str] = None, status: Optional[str] = None,
    ) -> List[AssessmentCollectionExecutionORM]:
        await self._get_run(customer_id, run_id)  # tenant check, 404 otherwise
        stmt = select(AssessmentCollectionExecutionORM).where(
            AssessmentCollectionExecutionORM.run_id == run_id
        )
        if target_id:
            stmt = stmt.where(AssessmentCollectionExecutionORM.target_id == target_id)
        if status:
            stmt = stmt.where(AssessmentCollectionExecutionORM.status == status)
        rows = (
            await self.db.execute(
                stmt.order_by(AssessmentCollectionExecutionORM.started_at)
            )
        ).scalars().all()
        return list(rows)

    async def list_results(
        self, customer_id: str, run_id: str, *,
        target_id: Optional[str] = None, status: Optional[str] = None,
        severity: Optional[str] = None, category: Optional[str] = None,
    ) -> List[AssessmentControlResultORM]:
        await self._get_run(customer_id, run_id)
        stmt = select(AssessmentControlResultORM).where(
            AssessmentControlResultORM.run_id == run_id
        )
        if target_id:
            stmt = stmt.where(AssessmentControlResultORM.target_id == target_id)
        if status:
            stmt = stmt.where(AssessmentControlResultORM.status == status)
        if severity:
            stmt = stmt.where(AssessmentControlResultORM.severity == severity)
        if category:
            stmt = stmt.where(AssessmentControlResultORM.category == category)
        rows = (
            await self.db.execute(
                stmt.order_by(AssessmentControlResultORM.control_id)
            )
        ).scalars().all()
        return list(rows)

    async def get_execution_evidence(
        self, customer_id: str, run_id: str, execution_id: str
    ) -> Dict[str, Any]:
        await self._get_run(customer_id, run_id)
        execution = (
            await self.db.execute(
                select(AssessmentCollectionExecutionORM).where(
                    AssessmentCollectionExecutionORM.id == execution_id,
                    AssessmentCollectionExecutionORM.run_id == run_id,
                )
            )
        ).scalar_one_or_none()
        if execution is None:
            raise APIError(404, "not_found", f"Execution '{execution_id}' not found")

        raw: Optional[Any] = None
        if execution.raw_evidence_sha:
            blob = (
                Path("data/evidence") / customer_id
                / f"{execution.raw_evidence_sha}.json"
            )
            if blob.exists():
                try:
                    raw = json.loads(blob.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    raw = blob.read_text(encoding="utf-8", errors="replace")

        return {
            "execution_id": execution.id,
            "step_id": execution.step_id,
            "tool_name": execution.tool_name,
            "raw": raw,
            "normalized": execution.normalized,
            "truncated": execution.truncated,
            "raw_size_bytes": execution.raw_size_bytes,
        }

    async def get_report(self, customer_id: str, run_id: str) -> AssessmentReportORM:
        await self._get_run(customer_id, run_id)
        report = (
            await self.db.execute(
                select(AssessmentReportORM).where(
                    AssessmentReportORM.run_id == run_id
                )
            )
        ).scalar_one_or_none()
        if report is None:
            raise APIError(404, "not_found",
                           "No report generated for this assessment yet")
        return report
