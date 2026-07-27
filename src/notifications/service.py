"""Outbound notification service (n8n webhook).

Best-effort by contract: no public method may raise into the ingestion/run
path (same guarantee as AuditService and GatewayAdminClient). Disabled
unless N8N_WEBHOOK_URL is set. Each delivery is persisted BEFORE the POST
so a failed or interrupted send can be resent from the UI with the exact
same payload.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from sqlalchemy import select

from src.config import settings
from src.core.database import async_session_factory
from src.core.models import Ticket
from src.core.orm import NotificationDeliveryORM, PlatformTenant
from src.notifications.payloads import (
    EVENT_RUN_COMPLETED,
    EVENT_TICKET_INGESTED,
    build_run_completed_payload,
    build_ticket_ingested_payload,
)

logger = logging.getLogger(__name__)

RESPONSE_BODY_MAX_CHARS = 4000


class NotificationService:
    """Dispatches notification events to the configured n8n webhook."""

    def is_configured(self) -> bool:
        return bool(settings.N8N_WEBHOOK_URL)

    # --- Event entry points (never raise) ---

    async def notify_ticket_ingested(self, ticket: Ticket, run_id: str, customer_id: str) -> None:
        """Fire ticket.ingested. Runs inside the HTTP request path: the row
        insert is awaited (so resend works even if the process dies), the
        POST is detached via create_task to keep request latency flat."""
        try:
            if not self.is_configured():
                logger.debug("Notifications disabled (N8N_WEBHOOK_URL unset); skipping ticket.ingested")
                return
            delivery_id = str(uuid.uuid4())
            payload = build_ticket_ingested_payload(
                event_id=delivery_id,
                customer_id=customer_id,
                tenant_name=await self._tenant_name(customer_id),
                ticket=ticket,
                run_id=run_id,
            )
            await self._persist_delivery(
                delivery_id, EVENT_TICKET_INGESTED, customer_id, ticket.id, run_id, payload
            )
            asyncio.create_task(self._dispatch(delivery_id))
        except Exception as e:
            logger.error(f"Notification: failed to emit ticket.ingested for run {run_id}: {e}")

    async def notify_run_completed(
        self, ticket: Ticket, run_id: str, customer_id: str, serializable_state: Dict[str, Any]
    ) -> None:
        """Fire run.completed with the full sanitized final state. Already
        runs in a background task, so the POST is awaited inline."""
        try:
            if not self.is_configured():
                logger.debug("Notifications disabled (N8N_WEBHOOK_URL unset); skipping run.completed")
                return
            delivery_id = str(uuid.uuid4())
            payload = build_run_completed_payload(
                event_id=delivery_id,
                customer_id=customer_id,
                tenant_name=await self._tenant_name(customer_id),
                ticket=ticket,
                run_id=run_id,
                serializable_state=serializable_state,
            )
            await self._persist_delivery(
                delivery_id, EVENT_RUN_COMPLETED, customer_id, ticket.id, run_id, payload
            )
            await self._dispatch(delivery_id)
        except Exception as e:
            logger.error(f"Notification: failed to emit run.completed for run {run_id}: {e}")

    # --- Resend (called from the API; raises KeyError/RuntimeError for the router to map) ---

    async def resend(self, delivery_id: str, customer_id: str) -> Optional[NotificationDeliveryORM]:
        """Re-POST the stored payload of a delivery (tenant-scoped).

        Returns the refreshed row, or None when no row matches the
        (delivery_id, customer_id) pair. Raises RuntimeError when the
        webhook is not configured.
        """
        if not self.is_configured():
            raise RuntimeError("not_configured")
        if await self._get_delivery(delivery_id, customer_id) is None:
            return None
        await self._dispatch(delivery_id)
        return await self._get_delivery(delivery_id, customer_id)

    # --- Internals ---

    async def _tenant_name(self, customer_id: str) -> Optional[str]:
        try:
            async with async_session_factory() as session:
                stmt = select(PlatformTenant.name).where(PlatformTenant.customer_id == customer_id)
                return (await session.execute(stmt)).scalar_one_or_none()
        except Exception as e:
            logger.warning(f"Notification: could not resolve tenant name for {customer_id}: {e}")
            return None

    async def _persist_delivery(
        self,
        delivery_id: str,
        event_type: str,
        customer_id: str,
        ticket_id: Optional[str],
        run_id: Optional[str],
        payload: Dict[str, Any],
    ) -> None:
        async with async_session_factory() as session:
            session.add(
                NotificationDeliveryORM(
                    id=delivery_id,
                    customer_id=customer_id,
                    event_type=event_type,
                    ticket_id=ticket_id,
                    run_id=run_id,
                    payload=payload,
                    status="pending",
                    attempts=0,
                )
            )
            await session.commit()

    async def _get_delivery(
        self, delivery_id: str, customer_id: Optional[str] = None
    ) -> Optional[NotificationDeliveryORM]:
        async with async_session_factory() as session:
            stmt = select(NotificationDeliveryORM).where(NotificationDeliveryORM.id == delivery_id)
            if customer_id is not None:
                stmt = stmt.where(NotificationDeliveryORM.customer_id == customer_id)
            return (await session.execute(stmt)).scalar_one_or_none()

    async def _dispatch(self, delivery_id: str) -> None:
        """POST the stored payload and record the attempt result. Never raises."""
        try:
            async with async_session_factory() as session:
                stmt = select(NotificationDeliveryORM).where(
                    NotificationDeliveryORM.id == delivery_id
                )
                row = (await session.execute(stmt)).scalar_one_or_none()
                if row is None:
                    logger.error(f"Notification: delivery {delivery_id} not found for dispatch")
                    return
                await self._apply_attempt(row)
                await session.commit()
        except Exception as e:
            logger.error(f"Notification: dispatch bookkeeping failed for {delivery_id}: {e}")

    async def _apply_attempt(self, row: NotificationDeliveryORM) -> None:
        """Execute one POST attempt against the stored payload and record the
        outcome on the row (no persistence here). Never raises."""
        row.attempts = (row.attempts or 0) + 1
        row.last_attempt_at = datetime.now(timezone.utc)
        try:
            response = await self._post(row.payload)
            row.response_status = response.status_code
            row.response_body = (response.text or "")[:RESPONSE_BODY_MAX_CHARS]
            if 200 <= response.status_code < 300:
                row.status = "delivered"
                row.error = None
            else:
                row.status = "failed"
                row.error = f"HTTP {response.status_code}"
        except Exception as e:
            row.status = "failed"
            row.error = str(e)
            logger.warning(f"Notification: delivery {row.id} failed: {e}")

    async def _post(self, payload: Dict[str, Any]) -> httpx.Response:
        headers = {}
        if settings.NOTIFICATION_AUTH_HEADER_NAME and settings.NOTIFICATION_AUTH_HEADER_VALUE:
            headers[settings.NOTIFICATION_AUTH_HEADER_NAME] = settings.NOTIFICATION_AUTH_HEADER_VALUE
        async with httpx.AsyncClient(timeout=settings.NOTIFICATION_TIMEOUT) as client:
            return await client.post(settings.N8N_WEBHOOK_URL, json=payload, headers=headers)
