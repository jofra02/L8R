from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from src.config import settings
from src.api.exceptions import register_exception_handlers
from src.utils.logger import setup_logging
import logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize logging first (must happen after uvicorn configures its own loggers)
    setup_logging()

    # Startup: same as legacy ingestion app
    from src.core.registry import CapabilityRegistry
    logger.info("Initializing Capability Registry and MCP tools...")
    CapabilityRegistry.load_builtin_packs()
    try:
        await CapabilityRegistry.load_external_tools()
        logger.info(f"Loaded {len(CapabilityRegistry.list_tools())} tools successfully.")
        await CapabilityRegistry.index_tools()
    except Exception as e:
        logger.error(f"Failed to load/index MCP tools during startup: {e}")
    yield
    # Shutdown: flush Langfuse
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

    # --- Public health endpoint (no auth) ---
    @application.get("/health")
    async def health_check():
        return {"status": "ok", "app": settings.APP_NAME}

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

    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(tickets_router, prefix="/api/v1")
    application.include_router(runs_router, prefix="/api/v1")
    application.include_router(audit_router, prefix="/api/v1")
    application.include_router(users_router, prefix="/api/v1")
    application.include_router(profiles_router, prefix="/api/v1")
    application.include_router(tenants_router, prefix="/api/v1")
    application.include_router(assignments_router, prefix="/api/v1")
    application.include_router(inventory_router, prefix="/api/v1")

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
