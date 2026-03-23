import asyncio
import math
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime

from src.api.dependencies import get_db, get_pagination, require_permission
from src.api.schemas.auth import AuthContext
from src.api.schemas.common import PaginationParams, PaginatedResponse
from src.api.schemas.tickets import (
    TicketSubmit, TicketListItem, TicketDetail, TicketTimelineEvent,
    EvidenceItem, HypothesisItem, FactItem, PlanResponse, TicketReportResponse,
    GlobalTicketListItem,
)
from src.api.exceptions import APIError
from src.core.orm import TicketORM, AgentRunORM, AgentEventORM, EvidenceRefORM

router = APIRouter(prefix="/tickets", tags=["tickets"])


# --- Helpers ---

def _latest_run_subquery():
    """Subquery to get the latest run per ticket for list views."""
    from sqlalchemy import desc
    return (
        select(
            AgentRunORM.ticket_id,
            AgentRunORM.id.label("latest_run_id"),
            AgentRunORM.status.label("latest_run_status"),
            AgentRunORM.decision.label("latest_run_decision"),
            AgentRunORM.final_answer.label("latest_run_final_answer"),
            func.row_number().over(
                partition_by=AgentRunORM.ticket_id,
                order_by=desc(AgentRunORM.started_at),
            ).label("rn"),
        )
        .subquery()
    )


async def _get_ticket_or_404(
    ticket_id: str, customer_id: str, db: AsyncSession
) -> TicketORM:
    stmt = select(TicketORM).where(
        TicketORM.id == ticket_id,
        TicketORM.customer_id == customer_id,
    )
    result = await db.execute(stmt)
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise APIError(404, "not_found", "Ticket not found")
    return ticket


async def _get_latest_run(
    ticket_id: str, customer_id: str, db: AsyncSession
) -> Optional[AgentRunORM]:
    stmt = (
        select(AgentRunORM)
        .where(
            AgentRunORM.ticket_id == ticket_id,
            AgentRunORM.customer_id == customer_id,
        )
        .order_by(AgentRunORM.started_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# --- Endpoints ---

@router.post("", status_code=202)
async def submit_ticket(
    body: TicketSubmit,
    auth: AuthContext = Depends(require_permission("tickets:write")),
    db: AsyncSession = Depends(get_db),
):
    """Submit a new ticket for pipeline processing. Returns 202 + ticket_id + job_id."""
    from src.ingestion.service import IngestionService
    from src.core import task_registry

    payload = {
        "text": body.text,
        "severity": body.severity,
        "mode": body.mode,
        "external_id": body.external_id,
        **(body.raw_payload or {}),
    }

    service = IngestionService(db)
    ticket, job_id = await service.ingest_webhook(body.source, payload, auth.customer_id)

    task = asyncio.create_task(
        service.run_pipeline_background(ticket=ticket, run_id=job_id, customer_id=auth.customer_id)
    )
    task_registry.register(job_id, task)

    return {
        "status": "accepted",
        "ticket_id": ticket.id,
        "job_id": job_id,
    }


@router.get("/global", response_model=PaginatedResponse[GlobalTicketListItem])
async def list_global_tickets(
    auth: AuthContext = Depends(require_permission("tickets:read")),
    pagination: PaginationParams = Depends(get_pagination),
    db: AsyncSession = Depends(get_db),
    severity: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="Filter by latest run status"),
    search: Optional[str] = Query(None, description="Search ticket text"),
    tenant: Optional[str] = Query(None, description="Filter by tenant customer_id"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    """List tickets across all tenants. Platform admin only."""
    if not auth.is_platform_admin:
        raise APIError(403, "platform_admin_required", "Requires platform admin")

    latest = _latest_run_subquery()

    base = (
        select(
            TicketORM,
            latest.c.latest_run_status,
            latest.c.latest_run_decision,
        )
        .outerjoin(
            latest,
            (latest.c.ticket_id == TicketORM.id) & (latest.c.rn == 1),
        )
    )

    if tenant:
        base = base.where(TicketORM.customer_id == tenant)
    if severity:
        base = base.where(TicketORM.severity == severity)
    if mode:
        base = base.where(TicketORM.mode == mode)
    if search:
        base = base.where(TicketORM.text.ilike(f"%{search}%"))
    if date_from:
        base = base.where(TicketORM.created_at >= date_from)
    if date_to:
        base = base.where(TicketORM.created_at <= date_to)
    if status:
        base = base.where(latest.c.latest_run_status == status)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    rows_stmt = (
        base
        .order_by(TicketORM.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    result = await db.execute(rows_stmt)
    rows = result.all()

    items = []
    for row in rows:
        ticket = row[0]
        items.append(GlobalTicketListItem(
            id=ticket.id,
            external_id=ticket.external_id,
            mode=ticket.mode,
            severity=ticket.severity,
            source=ticket.source,
            text=ticket.text,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
            latest_run_status=row[1],
            latest_run_decision=row[2],
            customer_id=ticket.customer_id,
        ))

    return PaginatedResponse(
        items=items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=math.ceil(total / pagination.page_size) if total else 0,
    )


@router.get("", response_model=PaginatedResponse[TicketListItem])
async def list_tickets(
    auth: AuthContext = Depends(require_permission("tickets:read")),
    pagination: PaginationParams = Depends(get_pagination),
    db: AsyncSession = Depends(get_db),
    severity: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="Filter by latest run status"),
    search: Optional[str] = Query(None, description="Search ticket text"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    """List tickets with pagination and filters."""
    latest = _latest_run_subquery()

    # Base query with left join to latest run
    base = (
        select(
            TicketORM,
            latest.c.latest_run_status,
            latest.c.latest_run_decision,
        )
        .outerjoin(
            latest,
            (latest.c.ticket_id == TicketORM.id) & (latest.c.rn == 1),
        )
        .where(TicketORM.customer_id == auth.customer_id)
    )

    # Apply filters
    if severity:
        base = base.where(TicketORM.severity == severity)
    if mode:
        base = base.where(TicketORM.mode == mode)
    if search:
        base = base.where(TicketORM.text.ilike(f"%{search}%"))
    if date_from:
        base = base.where(TicketORM.created_at >= date_from)
    if date_to:
        base = base.where(TicketORM.created_at <= date_to)
    if status:
        base = base.where(latest.c.latest_run_status == status)

    # Count
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Fetch page
    rows_stmt = (
        base
        .order_by(TicketORM.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    result = await db.execute(rows_stmt)
    rows = result.all()

    items = []
    for row in rows:
        ticket = row[0]
        items.append(TicketListItem(
            id=ticket.id,
            external_id=ticket.external_id,
            mode=ticket.mode,
            severity=ticket.severity,
            source=ticket.source,
            text=ticket.text,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
            latest_run_status=row[1],
            latest_run_decision=row[2],
        ))

    return PaginatedResponse(
        items=items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=math.ceil(total / pagination.page_size) if total else 0,
    )


@router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket_detail(
    ticket_id: str,
    auth: AuthContext = Depends(require_permission("tickets:read")),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _get_ticket_or_404(ticket_id, auth.customer_id, db)

    # Count runs
    count_stmt = select(func.count()).where(
        AgentRunORM.ticket_id == ticket_id,
        AgentRunORM.customer_id == auth.customer_id,
    )
    run_count = (await db.execute(count_stmt)).scalar() or 0

    latest_run = await _get_latest_run(ticket_id, auth.customer_id, db)

    return TicketDetail(
        id=ticket.id,
        external_id=ticket.external_id,
        mode=ticket.mode,
        severity=ticket.severity,
        source=ticket.source,
        text=ticket.text,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        raw_payload=ticket.raw_payload,
        run_count=run_count,
        latest_run_id=latest_run.id if latest_run else None,
        latest_run_status=latest_run.status if latest_run else None,
        latest_run_decision=latest_run.decision if latest_run else None,
        latest_run_final_answer=latest_run.final_answer if latest_run else None,
    )


@router.get("/{ticket_id}/timeline", response_model=list[TicketTimelineEvent])
async def get_ticket_timeline(
    ticket_id: str,
    auth: AuthContext = Depends(require_permission("tickets:read")),
    db: AsyncSession = Depends(get_db),
):
    """Agent events for all runs of this ticket, ordered by seq."""
    await _get_ticket_or_404(ticket_id, auth.customer_id, db)

    stmt = (
        select(AgentEventORM)
        .join(AgentRunORM, AgentEventORM.run_id == AgentRunORM.id)
        .where(
            AgentRunORM.ticket_id == ticket_id,
            AgentRunORM.customer_id == auth.customer_id,
        )
        .order_by(AgentEventORM.created_at, AgentEventORM.seq)
    )
    result = await db.execute(stmt)
    events = result.scalars().all()

    return [
        TicketTimelineEvent(
            id=e.id,
            run_id=e.run_id,
            seq=e.seq,
            node=e.node,
            created_at=e.created_at,
            input_summary=e.input_json,
            output_summary=e.output_json,
        )
        for e in events
    ]


@router.get("/{ticket_id}/evidence", response_model=list[EvidenceItem])
async def get_ticket_evidence(
    ticket_id: str,
    auth: AuthContext = Depends(require_permission("tickets:read")),
    db: AsyncSession = Depends(get_db),
):
    await _get_ticket_or_404(ticket_id, auth.customer_id, db)

    stmt = (
        select(EvidenceRefORM)
        .where(
            EvidenceRefORM.ticket_id == ticket_id,
            EvidenceRefORM.customer_id == auth.customer_id,
        )
        .order_by(EvidenceRefORM.created_at)
    )
    result = await db.execute(stmt)
    return [EvidenceItem.model_validate(e) for e in result.scalars().all()]


@router.get("/{ticket_id}/hypotheses", response_model=list[HypothesisItem])
async def get_ticket_hypotheses(
    ticket_id: str,
    auth: AuthContext = Depends(require_permission("tickets:read")),
    db: AsyncSession = Depends(get_db),
):
    """Extract hypotheses from the latest run's state_json."""
    await _get_ticket_or_404(ticket_id, auth.customer_id, db)
    run = await _get_latest_run(ticket_id, auth.customer_id, db)
    if not run or not run.state_json:
        return []

    raw = run.state_json.get("hypotheses", [])
    items = []
    for h in raw:
        if isinstance(h, dict):
            items.append(HypothesisItem(
                id=h.get("id"),
                title=h.get("title", ""),
                description=h.get("description", ""),
                confidence=h.get("confidence"),
                status=h.get("status"),
                evidence_refs=h.get("evidence_refs", []),
            ))
    return items


@router.get("/{ticket_id}/facts", response_model=list[FactItem])
async def get_ticket_facts(
    ticket_id: str,
    auth: AuthContext = Depends(require_permission("tickets:read")),
    db: AsyncSession = Depends(get_db),
):
    """Extract structured facts from the latest run's state_json."""
    await _get_ticket_or_404(ticket_id, auth.customer_id, db)
    run = await _get_latest_run(ticket_id, auth.customer_id, db)
    if not run or not run.state_json:
        return []

    raw_facts = run.state_json.get("facts", {})
    structured = run.state_json.get("structured_facts", [])

    # Prefer structured_facts if available
    if structured and isinstance(structured, list):
        items = []
        for f in structured:
            if isinstance(f, dict):
                items.append(FactItem(
                    key=f.get("key", ""),
                    value=f.get("value"),
                    source_evidence_id=f.get("source_evidence_id"),
                    confidence=f.get("confidence"),
                ))
        return items

    # Fallback to flat facts dict
    return [FactItem(key=k, value=v) for k, v in raw_facts.items()]


@router.get("/{ticket_id}/plan", response_model=PlanResponse)
async def get_ticket_plan(
    ticket_id: str,
    auth: AuthContext = Depends(require_permission("tickets:read")),
    db: AsyncSession = Depends(get_db),
):
    """Extract resolution plan from the latest run's state_json."""
    await _get_ticket_or_404(ticket_id, auth.customer_id, db)
    run = await _get_latest_run(ticket_id, auth.customer_id, db)
    if not run or not run.state_json:
        return PlanResponse()

    plan = run.state_json.get("plan")
    if not plan or not isinstance(plan, dict):
        return PlanResponse()

    return PlanResponse(
        diagnosis_steps=plan.get("diagnosis_steps", []),
        remediation_steps=plan.get("remediation_steps", []),
        validation_steps=plan.get("validation_steps", []),
        rollback_steps=plan.get("rollback_steps", []),
    )


@router.get("/{ticket_id}/report", response_model=TicketReportResponse)
async def get_ticket_report(
    ticket_id: str,
    auth: AuthContext = Depends(require_permission("tickets:read")),
    db: AsyncSession = Depends(get_db),
):
    await _get_ticket_or_404(ticket_id, auth.customer_id, db)
    run = await _get_latest_run(ticket_id, auth.customer_id, db)
    if not run:
        raise APIError(404, "not_found", "No runs found for this ticket")

    final_answer = ""
    if run.final_answer:
        final_answer = run.final_answer
    elif run.state_json:
        final_answer = run.state_json.get("final_answer", "")

    return TicketReportResponse(
        ticket_id=ticket_id,
        job_id=run.id,
        status=run.status,
        report=final_answer,
    )


@router.post("/{ticket_id}/retry", status_code=202)
async def retry_ticket(
    ticket_id: str,
    auth: AuthContext = Depends(require_permission("tickets:write")),
    db: AsyncSession = Depends(get_db),
):
    """Re-run the pipeline for an existing ticket."""
    from src.core.models import Ticket as TicketModel
    from src.core import task_registry
    ticket_orm = await _get_ticket_or_404(ticket_id, auth.customer_id, db)

    from src.ingestion.service import IngestionService
    service = IngestionService(db)

    # Create a new run via audit
    import uuid
    trace_id = str(uuid.uuid4())
    job_id = await service.audit.create_run(ticket_id, trace_id, auth.customer_id)

    # Reconstruct domain Ticket from ORM
    ticket = TicketModel(
        id=ticket_orm.id,
        mode=ticket_orm.mode,
        text=ticket_orm.text,
        severity=ticket_orm.severity,
        source=ticket_orm.source,
        raw_payload=ticket_orm.raw_payload or {},
    )

    task = asyncio.create_task(
        service.run_pipeline_background(ticket=ticket, run_id=job_id, customer_id=auth.customer_id)
    )
    task_registry.register(job_id, task)

    return {
        "status": "accepted",
        "ticket_id": ticket_id,
        "job_id": job_id,
    }
