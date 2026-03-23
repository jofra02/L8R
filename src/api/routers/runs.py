import math
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, extract, case
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime

from src.api.dependencies import get_db, get_pagination, require_permission
from src.api.schemas.auth import AuthContext
from src.api.schemas.common import PaginationParams, PaginatedResponse
from src.api.schemas.runs import (
    RunListItem, RunDetail, RunTimelineEvent, RunToolCall, RunStats,
)
from src.api.exceptions import APIError
from src.core.orm import AgentRunORM, AgentEventORM, ToolCallAuditORM
from src.core import task_registry

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=PaginatedResponse[RunListItem])
async def list_runs(
    auth: AuthContext = Depends(require_permission("runs:read")),
    pagination: PaginationParams = Depends(get_pagination),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None),
    ticket_id: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    base = select(AgentRunORM).where(AgentRunORM.customer_id == auth.customer_id)

    if status:
        base = base.where(AgentRunORM.status == status)
    if ticket_id:
        base = base.where(AgentRunORM.ticket_id == ticket_id)
    if date_from:
        base = base.where(AgentRunORM.started_at >= date_from)
    if date_to:
        base = base.where(AgentRunORM.started_at <= date_to)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    rows_stmt = (
        base
        .order_by(AgentRunORM.started_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    result = await db.execute(rows_stmt)
    runs = result.scalars().all()

    return PaginatedResponse(
        items=[RunListItem.model_validate(r) for r in runs],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=math.ceil(total / pagination.page_size) if total else 0,
    )


@router.get("/stats", response_model=RunStats)
async def get_run_stats(
    auth: AuthContext = Depends(require_permission("runs:read")),
    db: AsyncSession = Depends(get_db),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    """Aggregate run statistics for the tenant."""
    base_filter = [AgentRunORM.customer_id == auth.customer_id]
    if date_from:
        base_filter.append(AgentRunORM.started_at >= date_from)
    if date_to:
        base_filter.append(AgentRunORM.started_at <= date_to)

    # Total + by status
    status_stmt = (
        select(AgentRunORM.status, func.count())
        .where(*base_filter)
        .group_by(AgentRunORM.status)
    )
    status_result = await db.execute(status_stmt)
    by_status = {row[0]: row[1] for row in status_result.all()}
    total_runs = sum(by_status.values())

    # By decision
    decision_stmt = (
        select(AgentRunORM.decision, func.count())
        .where(*base_filter, AgentRunORM.decision.isnot(None))
        .group_by(AgentRunORM.decision)
    )
    decision_result = await db.execute(decision_stmt)
    by_decision = {row[0]: row[1] for row in decision_result.all()}

    # Avg duration (completed runs only)
    avg_stmt = (
        select(
            func.avg(
                extract("epoch", AgentRunORM.ended_at) - extract("epoch", AgentRunORM.started_at)
            )
        )
        .where(
            *base_filter,
            AgentRunORM.status == "completed",
            AgentRunORM.ended_at.isnot(None),
        )
    )
    avg_duration = (await db.execute(avg_stmt)).scalar()

    completed = by_status.get("completed", 0)
    success_rate = (completed / total_runs) if total_runs > 0 else None

    return RunStats(
        total_runs=total_runs,
        by_status=by_status,
        by_decision=by_decision,
        avg_duration_seconds=round(avg_duration, 2) if avg_duration else None,
        success_rate=round(success_rate, 4) if success_rate is not None else None,
    )


@router.get("/{run_id}", response_model=RunDetail)
async def get_run_detail(
    run_id: str,
    auth: AuthContext = Depends(require_permission("runs:read")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AgentRunORM).where(
        AgentRunORM.id == run_id,
        AgentRunORM.customer_id == auth.customer_id,
    )
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    if not run:
        raise APIError(404, "not_found", "Run not found")

    return RunDetail(
        id=run.id,
        ticket_id=run.ticket_id,
        trace_id=run.trace_id,
        status=run.status,
        decision=run.decision,
        hypothesis_count=run.hypothesis_count,
        final_answer=run.final_answer,
        cost_json=run.cost_json,
        state_json=run.state_json,
        started_at=run.started_at,
        ended_at=run.ended_at,
    )


@router.get("/{run_id}/timeline", response_model=list[RunTimelineEvent])
async def get_run_timeline(
    run_id: str,
    auth: AuthContext = Depends(require_permission("runs:read")),
    db: AsyncSession = Depends(get_db),
):
    # Verify run belongs to tenant
    run_check = select(AgentRunORM.id).where(
        AgentRunORM.id == run_id,
        AgentRunORM.customer_id == auth.customer_id,
    )
    if not (await db.execute(run_check)).scalar():
        raise APIError(404, "not_found", "Run not found")

    stmt = (
        select(AgentEventORM)
        .where(AgentEventORM.run_id == run_id)
        .order_by(AgentEventORM.seq)
    )
    result = await db.execute(stmt)
    return [RunTimelineEvent.model_validate(e) for e in result.scalars().all()]


@router.get("/{run_id}/tool-calls", response_model=list[RunToolCall])
async def get_run_tool_calls(
    run_id: str,
    auth: AuthContext = Depends(require_permission("runs:read")),
    db: AsyncSession = Depends(get_db),
):
    # Verify run belongs to tenant
    run_check = select(AgentRunORM.id).where(
        AgentRunORM.id == run_id,
        AgentRunORM.customer_id == auth.customer_id,
    )
    if not (await db.execute(run_check)).scalar():
        raise APIError(404, "not_found", "Run not found")

    stmt = (
        select(ToolCallAuditORM)
        .where(ToolCallAuditORM.run_id == run_id)
        .order_by(ToolCallAuditORM.started_at)
    )
    result = await db.execute(stmt)
    return [RunToolCall.model_validate(tc) for tc in result.scalars().all()]


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    auth: AuthContext = Depends(require_permission("runs:read")),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running pipeline execution."""
    stmt = select(AgentRunORM).where(
        AgentRunORM.id == run_id,
        AgentRunORM.customer_id == auth.customer_id,
    )
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    if not run:
        raise APIError(404, "not_found", "Run not found")

    if run.status != "running":
        raise APIError(409, "invalid_state", f"Run is not running (current status: {run.status})")

    cancelled = task_registry.cancel(run_id)
    if not cancelled:
        # Task not in registry (process restarted, etc.) — update DB directly
        from src.core.audit import AuditService
        audit = AuditService()
        await audit.complete_run(run_id, "cancelled")

    return {"status": "cancelled", "run_id": run_id}
