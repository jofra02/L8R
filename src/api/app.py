import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from src.config import settings
from src.api.exceptions import register_exception_handlers
from src.utils.logger import setup_logging
import logging

logger = logging.getLogger(__name__)


async def _index_tools_background(app: FastAPI) -> None:
    """Index the tool catalog without blocking startup.

    On a cold Qdrant this classifies ~2200 tools via LLM (minutes); running it
    inside the lifespan kept uvicorn from serving /health and the Docker
    healthcheck marked the app unhealthy on first boot.
    """
    from src.core.registry import CapabilityRegistry
    state = app.state.tool_indexing
    state["status"] = "indexing"
    try:
        await CapabilityRegistry.index_tools()
        state["status"] = "done"
        logger.info("Tool catalog indexing complete.")
    except Exception as e:
        state["status"] = "failed"
        state["error"] = str(e)
        logger.error(f"Tool catalog indexing failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize logging first (must happen after uvicorn configures its own loggers)
    setup_logging()

    # Startup: same as legacy ingestion app
    from src.core.registry import CapabilityRegistry
    logger.info("Initializing Capability Registry and MCP tools...")
    app.state.tool_indexing = {"status": "pending", "error": None}
    CapabilityRegistry.load_builtin_packs()
    try:
        await CapabilityRegistry.load_external_tools()
        logger.info(f"Loaded {len(CapabilityRegistry.list_tools())} tools successfully.")
    except Exception as e:
        logger.error(f"Failed to load MCP tools during startup: {e}")
    index_task = asyncio.create_task(_index_tools_background(app))

    # Device Assessment module: sync YAML definitions to their immutable DB
    # snapshots and fail runs orphaned by a previous process (in-memory task
    # registry cannot resume them). Best-effort: a down DB must not block boot.
    if settings.ASSESSMENT_ENABLED:
        try:
            from src.assessments.registry import sync_definitions
            from src.assessments.runner import sweep_stale_runs
            from src.core.database import async_session_factory
            async with async_session_factory() as session:
                outcome = await sync_definitions(session)
            logger.info(f"Assessment definitions synced: {outcome}")
            await sweep_stale_runs()
        except Exception as e:
            logger.error(f"Assessment startup (definition sync / stale sweep) failed: {e}")

    yield
    # Shutdown: stop indexing if still running, flush Langfuse
    if not index_task.done():
        index_task.cancel()
    from src.core.langfuse_integration import langfuse_manager
    langfuse_manager.flush()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version="0.2.0",
        lifespan=lifespan,
    )

    # CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    register_exception_handlers(application)

    # --- Public health endpoints (no auth) ---
    @application.get("/health")
    async def health_check():
        # Liveness only: the process is up and serving
        return {"status": "ok", "app": settings.APP_NAME}

    @application.get("/ready")
    async def readiness_check():
        # Readiness: surfaces background tool-catalog indexing state.
        # The API is usable before indexing finishes; search_tool_catalog
        # may return partial results until status is "done".
        indexing = getattr(application.state, "tool_indexing", {"status": "pending", "error": None})
        status_map = {"done": "ready", "failed": "degraded"}
        return {
            "status": status_map.get(indexing["status"], "initializing"),
            "app": settings.APP_NAME,
            "tool_indexing": indexing,
        }

    # --- Mount API v1 routers ---
    from src.api.routers.auth import router as auth_router
    from src.api.routers.tickets import router as tickets_router
    from src.api.routers.runs import router as runs_router
    from src.api.routers.audit import router as audit_router
    from src.api.routers.users import router as users_router
    from src.api.routers.profiles import router as profiles_router
    from src.api.routers.tenants import router as tenants_router
    from src.api.routers.assignments import router as assignments_router
    from src.api.routers.inventory import router as inventory_router
    from src.api.routers.assessments import (
        router as assessments_router,
        definitions_router as assessment_definitions_router,
    )

    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(tickets_router, prefix="/api/v1")
    application.include_router(runs_router, prefix="/api/v1")
    application.include_router(audit_router, prefix="/api/v1")
    application.include_router(users_router, prefix="/api/v1")
    application.include_router(profiles_router, prefix="/api/v1")
    application.include_router(tenants_router, prefix="/api/v1")
    application.include_router(assignments_router, prefix="/api/v1")
    application.include_router(inventory_router, prefix="/api/v1")
    if settings.ASSESSMENT_ENABLED:
        application.include_router(assessments_router, prefix="/api/v1")
        application.include_router(assessment_definitions_router, prefix="/api/v1")

    # --- Legacy webhook (backward compat with X-Customer-ID header) ---
    _mount_legacy_webhook(application)

    return application


def _mount_legacy_webhook(application: FastAPI) -> None:
    """Mount legacy ingestion endpoints for backward compatibility."""
    import asyncio
    from fastapi import Depends, HTTPException, Body, Header
    from sqlalchemy.ext.asyncio import AsyncSession
    from typing import Dict, Any
    from src.core.database import get_session
    from src.ingestion.service import IngestionService
    from src.core import task_registry

    async def _get_service(session: AsyncSession = Depends(get_session)) -> IngestionService:
        return IngestionService(session)

    @application.post("/api/v1/webhook/{source_id}", status_code=202, tags=["legacy"])
    async def receive_webhook(
        source_id: str,
        payload: Dict[str, Any] = Body(...),
        customer_id: str = Header(..., alias="X-Customer-ID"),
        service: IngestionService = Depends(_get_service),
    ):
        if not customer_id:
            raise HTTPException(status_code=400, detail="Missing X-Customer-ID header")
        ticket, job_id = await service.ingest_webhook(source_id, payload, customer_id)
        task = asyncio.create_task(
            service.run_pipeline_background(ticket=ticket, run_id=job_id, customer_id=customer_id)
        )
        task_registry.register(job_id, task)
        return {
            "status": "accepted",
            "message": "Ticket ingested. Processing launched in background.",
            "ticket_id": ticket.id,
            "job_id": job_id,
        }

    @application.get("/api/v1/jobs/{job_id}", tags=["legacy"])
    async def get_job_status(
        job_id: str,
        customer_id: str = Header(None, alias="X-Customer-ID"),
        service: IngestionService = Depends(_get_service),
    ):
        status = await service.get_job_status(job_id, customer_id=customer_id)
        if not status:
            raise HTTPException(status_code=404, detail="Job not found")
        return status


app = create_app()
