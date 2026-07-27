import math
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from src.api.dependencies import get_db, get_pagination, require_permission
from src.api.schemas.auth import AuthContext
from src.api.schemas.common import PaginationParams, PaginatedResponse
from src.api.schemas.notifications import NotificationDeliveryItem
from src.api.exceptions import APIError
from src.core.orm import NotificationDeliveryORM
from src.notifications import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=PaginatedResponse[NotificationDeliveryItem])
async def list_notifications(
    auth: AuthContext = Depends(require_permission("notifications:read")),
    pagination: PaginationParams = Depends(get_pagination),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    ticket_id: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
):
    base = select(NotificationDeliveryORM).where(
        NotificationDeliveryORM.customer_id == auth.customer_id
    )
    if status:
        base = base.where(NotificationDeliveryORM.status == status)
    if event_type:
        base = base.where(NotificationDeliveryORM.event_type == event_type)
    if ticket_id:
        base = base.where(NotificationDeliveryORM.ticket_id == ticket_id)
    if run_id:
        base = base.where(NotificationDeliveryORM.run_id == run_id)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    rows_stmt = (
        base
        .order_by(NotificationDeliveryORM.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    return PaginatedResponse(
        items=[NotificationDeliveryItem.model_validate(r) for r in rows],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=math.ceil(total / pagination.page_size) if total else 0,
    )


@router.post("/{delivery_id}/resend", response_model=NotificationDeliveryItem)
async def resend_notification(
    delivery_id: str,
    auth: AuthContext = Depends(require_permission("notifications:manage")),
):
    service = NotificationService()
    try:
        row = await service.resend(delivery_id, auth.customer_id)
    except RuntimeError:
        raise APIError(409, "not_configured", "Outbound notifications are not configured (N8N_WEBHOOK_URL unset)")
    if row is None:
        raise APIError(404, "not_found", f"Notification delivery {delivery_id} not found")
    return NotificationDeliveryItem.model_validate(row)
