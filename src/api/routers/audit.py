import math
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime

from src.api.dependencies import get_db, get_pagination, require_permission
from src.api.schemas.auth import AuthContext
from src.api.schemas.common import PaginationParams, PaginatedResponse
from src.api.schemas.audit import AuditLogResponse, ToolCallResponse
from src.core.orm import AuditLogORM, ToolCallAuditORM, AgentRunORM

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs", response_model=PaginatedResponse[AuditLogResponse])
async def query_audit_logs(
    auth: AuthContext = Depends(require_permission("audit:read")),
    pagination: PaginationParams = Depends(get_pagination),
    db: AsyncSession = Depends(get_db),
    ticket_id: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    base = select(AuditLogORM).where(AuditLogORM.customer_id == auth.customer_id)

    if ticket_id:
        base = base.where(AuditLogORM.ticket_id == ticket_id)
    if actor:
        base = base.where(AuditLogORM.actor == actor)
    if action:
        base = base.where(AuditLogORM.action == action)
    if date_from:
        base = base.where(AuditLogORM.timestamp >= date_from)
    if date_to:
        base = base.where(AuditLogORM.timestamp <= date_to)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    rows_stmt = (
        base
        .order_by(AuditLogORM.timestamp.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    result = await db.execute(rows_stmt)
    logs = result.scalars().all()

    return PaginatedResponse(
        items=[AuditLogResponse.model_validate(l) for l in logs],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=math.ceil(total / pagination.page_size) if total else 0,
    )


@router.get("/tool-calls", response_model=PaginatedResponse[ToolCallResponse])
async def query_tool_calls(
    auth: AuthContext = Depends(require_permission("audit:read")),
    pagination: PaginationParams = Depends(get_pagination),
    db: AsyncSession = Depends(get_db),
    run_id: Optional[str] = Query(None),
    tool_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    base = (
        select(ToolCallAuditORM)
        .join(AgentRunORM, ToolCallAuditORM.run_id == AgentRunORM.id)
        .where(AgentRunORM.customer_id == auth.customer_id)
    )

    if run_id:
        base = base.where(ToolCallAuditORM.run_id == run_id)
    if tool_name:
        base = base.where(ToolCallAuditORM.tool_name == tool_name)
    if status:
        base = base.where(ToolCallAuditORM.status == status)
    if date_from:
        base = base.where(ToolCallAuditORM.started_at >= date_from)
    if date_to:
        base = base.where(ToolCallAuditORM.started_at <= date_to)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    rows_stmt = (
        base
        .order_by(ToolCallAuditORM.started_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    result = await db.execute(rows_stmt)
    tool_calls = result.scalars().all()

    return PaginatedResponse(
        items=[ToolCallResponse.model_validate(tc) for tc in tool_calls],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=math.ceil(total / pagination.page_size) if total else 0,
    )
