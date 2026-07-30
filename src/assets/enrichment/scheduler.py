"""Periodic re-enrichment scheduler (in-process asyncio loop).

Minimal by design: no cron, no external queue — dies with the process and
is reconciled by sweep_stale_sync_runs + the next tick. Every
ASSETS_SYNC_INTERVAL_HOURS each managed asset without an active run whose
last run finished before the interval (or that never ran) is re-enqueued
with trigger="scheduled". ASSETS_SYNC_INTERVAL_HOURS=0 disables the loop.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from src.assets.enrichment.engine import ACTIVE_STATUSES, enqueue_enrichment
from src.config import settings
from src.core import task_registry
from src.core.database import async_session_factory
from src.core.orm import AssetORM, AssetSyncRunORM

logger = logging.getLogger(__name__)

_TASK_KEY = "assets-enrichment-scheduler"
TICK_SECONDS = 900  # candidate scan cadence; the interval gates actual runs


def start_scheduler() -> Optional[asyncio.Task]:
    if settings.ASSETS_SYNC_INTERVAL_HOURS <= 0:
        logger.info("Asset enrichment scheduler disabled (ASSETS_SYNC_INTERVAL_HOURS=0)")
        return None
    task = asyncio.create_task(_loop())
    task_registry.register(_TASK_KEY, task)
    logger.info(
        f"Asset enrichment scheduler started "
        f"(every {settings.ASSETS_SYNC_INTERVAL_HOURS}h, tick {TICK_SECONDS}s)"
    )
    return task


async def _loop() -> None:
    try:
        while True:
            try:
                queued = await tick()
                if queued:
                    logger.info(f"Enrichment scheduler queued {queued} run(s)")
            except Exception as e:
                logger.error(f"Enrichment scheduler tick failed: {e}")
            await asyncio.sleep(TICK_SECONDS)
    except asyncio.CancelledError:
        pass
    finally:
        task_registry.unregister(_TASK_KEY)


async def tick(now: Optional[datetime] = None) -> int:
    """One scheduler pass. Returns the number of runs queued."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=settings.ASSETS_SYNC_INTERVAL_HOURS)
    queued = 0

    async with async_session_factory() as session:
        assets = (await session.execute(
            select(AssetORM.id, AssetORM.customer_id).where(
                AssetORM.managed.is_(True),
                AssetORM.deleted_at.is_(None),
            )
        )).all()

        candidates = []
        for asset_id, customer_id in assets:
            last = (await session.execute(
                select(AssetSyncRunORM)
                .where(AssetSyncRunORM.asset_id == asset_id)
                .order_by(AssetSyncRunORM.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if last is not None and last.status in ACTIVE_STATUSES:
                continue
            reference = (last.finished_at or last.created_at) if last else None
            if reference is not None and reference.tzinfo is None:
                # sqlite (tests) returns naive datetimes; stored values are UTC
                reference = reference.replace(tzinfo=timezone.utc)
            if reference is None or reference <= cutoff:
                candidates.append((customer_id, asset_id))

    for customer_id, asset_id in candidates:
        try:
            await enqueue_enrichment(customer_id, asset_id, trigger="scheduled")
            queued += 1
        except Exception as e:
            logger.debug(f"scheduler: asset {asset_id} not queued — {e}")
    return queued
