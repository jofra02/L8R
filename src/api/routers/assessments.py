"""Device Assessment API endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import (
    get_db,
    get_pagination,
    require_permission,
    require_tenant_permission,
)
from src.api.exceptions import APIError
from src.api.schemas.assessment import (
    AssessmentCreate,
    AssessmentCreateResponse,
    AssessmentDetail,
    AssessmentListItem,
    ControlResultResponse,
    DefinitionVersionDetail,
    DefinitionVersionItem,
    EvidenceResponse,
    ExecutionResponse,
    ReportResponse,
    TargetResponse,
)
from src.api.schemas.auth import AuthContext
from src.api.schemas.common import PaginatedResponse, PaginationParams
from src.api.services.assessment_service import AssessmentService

router = APIRouter(prefix="/assessments", tags=["assessments"])

definitions_router = APIRouter(
    prefix="/assessment-definitions", tags=["assessments"]
)


def _svc(db: AsyncSession) -> AssessmentService:
    return AssessmentService(db)


def _detail(run, targets, device_count: Optional[int] = None) -> AssessmentDetail:
    # Never model_validate AssessmentDetail from the ORM object: its `targets`
    # field would trigger an async lazy-load of the relationship outside the
    # session (MissingGreenlet). Targets are queried explicitly by the service.
    base = AssessmentListItem.model_validate(run)
    data = base.model_dump()
    data["device_count"] = device_count if device_count is not None else len(targets)
    return AssessmentDetail(
        **data,
        params=run.params or {},
        error=run.error,
        targets=[TargetResponse.model_validate(t) for t in targets],
    )


# --- Definitions ---

@definitions_router.get("", response_model=list[DefinitionVersionItem])
async def list_definitions(
    auth: AuthContext = Depends(require_permission("assessments:read")),
    db: AsyncSession = Depends(get_db),
):
    return [
        DefinitionVersionItem.model_validate(row)
        for row in await _svc(db).list_definitions()
    ]


@definitions_router.get(
    "/{definition_id}/versions/{version}", response_model=DefinitionVersionDetail
)
async def get_definition_version(
    definition_id: str,
    version: str,
    auth: AuthContext = Depends(require_permission("assessments:read")),
    db: AsyncSession = Depends(get_db),
):
    row = await _svc(db).get_definition_version(definition_id, version)
    content = row.content or {}
    controls = content.get("controls", [])
    categories: list[str] = []
    for c in controls:
        if c.get("category") and c["category"] not in categories:
            categories.append(c["category"])
    return DefinitionVersionDetail(
        **DefinitionVersionItem.model_validate(row).model_dump(),
        step_count=len(content.get("collection_steps", [])),
        control_count=len(controls),
        categories=categories,
        collection_steps=content.get("collection_steps", []),
        controls=controls,
    )


# --- Run lifecycle ---

@router.post("", response_model=AssessmentCreateResponse, status_code=201)
async def create_assessment(
    body: AssessmentCreate,
    auth: AuthContext = Depends(require_tenant_permission("assessments:write")),
    db: AsyncSession = Depends(get_db),
):
    run, targets, warnings = await _svc(db).create_run(
        auth.customer_id, body, requested_by=auth.user_id
    )
    return AssessmentCreateResponse(run=_detail(run, targets), warnings=warnings)


@router.post("/{run_id}/start", response_model=AssessmentDetail)
async def start_assessment(
    run_id: str,
    auth: AuthContext = Depends(require_tenant_permission("assessments:write")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    await svc.start_run(auth.customer_id, run_id)
    run, targets = await svc.get_run_detail(auth.customer_id, run_id)
    return _detail(run, targets)


@router.post("/{run_id}/cancel", response_model=AssessmentDetail)
async def cancel_assessment(
    run_id: str,
    auth: AuthContext = Depends(require_tenant_permission("assessments:write")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    await svc.cancel_run(auth.customer_id, run_id)
    run, targets = await svc.get_run_detail(auth.customer_id, run_id)
    return _detail(run, targets)


@router.post("/{run_id}/reevaluate", response_model=AssessmentDetail)
async def reevaluate_assessment(
    run_id: str,
    auth: AuthContext = Depends(require_tenant_permission("assessments:write")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    await svc.reevaluate_run(auth.customer_id, run_id)
    run, targets = await svc.get_run_detail(auth.customer_id, run_id)
    return _detail(run, targets)


# --- Queries ---

@router.get("", response_model=PaginatedResponse[AssessmentListItem])
async def list_assessments(
    status: Optional[str] = Query(None),
    definition_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    pagination: PaginationParams = Depends(get_pagination),
    auth: AuthContext = Depends(require_tenant_permission("assessments:read")),
    db: AsyncSession = Depends(get_db),
):
    rows, counts, total, total_pages = await _svc(db).list_runs(
        auth.customer_id,
        page=pagination.page, page_size=pagination.page_size,
        status=status, definition_id=definition_id, search=search,
    )
    items = []
    for row in rows:
        item = AssessmentListItem.model_validate(row)
        item.device_count = counts.get(row.id, 0)
        items.append(item)
    return PaginatedResponse(
        items=items, total=total,
        page=pagination.page, page_size=pagination.page_size,
        total_pages=total_pages,
    )


@router.get("/{run_id}", response_model=AssessmentDetail)
async def get_assessment(
    run_id: str,
    auth: AuthContext = Depends(require_tenant_permission("assessments:read")),
    db: AsyncSession = Depends(get_db),
):
    run, targets = await _svc(db).get_run_detail(auth.customer_id, run_id)
    return _detail(run, targets)


@router.get("/{run_id}/steps", response_model=list[ExecutionResponse])
async def list_assessment_steps(
    run_id: str,
    target_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    auth: AuthContext = Depends(require_tenant_permission("assessments:read")),
    db: AsyncSession = Depends(get_db),
):
    rows = await _svc(db).list_executions(
        auth.customer_id, run_id, target_id=target_id, status=status
    )
    return [ExecutionResponse.model_validate(r) for r in rows]


@router.get("/{run_id}/results", response_model=list[ControlResultResponse])
async def list_assessment_results(
    run_id: str,
    target_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    auth: AuthContext = Depends(require_tenant_permission("assessments:read")),
    db: AsyncSession = Depends(get_db),
):
    rows = await _svc(db).list_results(
        auth.customer_id, run_id,
        target_id=target_id, status=status, severity=severity, category=category,
    )
    return [ControlResultResponse.model_validate(r) for r in rows]


@router.get(
    "/{run_id}/executions/{execution_id}/evidence", response_model=EvidenceResponse
)
async def get_execution_evidence(
    run_id: str,
    execution_id: str,
    auth: AuthContext = Depends(require_tenant_permission("assessments:read")),
    db: AsyncSession = Depends(get_db),
):
    data = await _svc(db).get_execution_evidence(
        auth.customer_id, run_id, execution_id
    )
    return EvidenceResponse(**data)


@router.get("/{run_id}/report", response_model=ReportResponse)
async def get_assessment_report(
    run_id: str,
    auth: AuthContext = Depends(require_tenant_permission("assessments:read")),
    db: AsyncSession = Depends(get_db),
):
    report = await _svc(db).get_report(auth.customer_id, run_id)
    return ReportResponse(
        run_id=report.run_id,
        format_version=report.format_version,
        generated_at=report.generated_at,
        model=report.model,
    )
