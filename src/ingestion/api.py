from fastapi import FastAPI, Depends, HTTPException, Query, Body, Header, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional
from src.core.database import get_session
from src.ingestion.service import IngestionService
from src.config import settings
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load tools
    from src.core.registry import CapabilityRegistry
    logger.info("Initializing Capability Registry and MCP tools...")
    CapabilityRegistry.load_builtin_packs()
    try:
        await CapabilityRegistry.load_external_tools()
        logger.info(f"Loaded {len(CapabilityRegistry.list_tools())} tools successfully.")
    except Exception as e:
        logger.error(f"Failed to load external MCP tools during startup: {e}")
    yield
    # Shutdown logic
    pass

app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)

# --- Dependencies ---

async def get_ingestion_service(session: AsyncSession = Depends(get_session)) -> IngestionService:
    return IngestionService(session)

# --- Endpoints ---

@app.get("/health")
async def health_check():
    """Simple health check."""
    return {"status": "ok", "app": settings.APP_NAME}

@app.post("/api/v1/webhook/{source_id}", status_code=202)
async def receive_webhook(
    source_id: str,
    background_tasks: BackgroundTasks,
    payload: Dict[str, Any] = Body(...),
    customer_id: str = Header(..., alias="X-Customer-ID"),
    service: IngestionService = Depends(get_ingestion_service)
):
    """
    Ingest a ticket via webhook asynchronously.
    Returns 202 Accepted right away.
    """
    try:
        if not customer_id:
            raise HTTPException(status_code=400, detail="Missing X-Customer-ID header")
            
        ticket_id, job_id, text = await service.ingest_webhook(source_id, payload, customer_id)
        
        # Dispatch the backend execution
        background_tasks.add_task(
            service.run_pipeline_background,
            ticket_id=ticket_id,
            run_id=job_id,
            customer_id=customer_id,
            text=text
        )
        
        return {
            "status": "accepted",
            "message": "Ticket ingested. Processing launched in background.",
            "ticket_id": ticket_id,
            "job_id": job_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    customer_id: str = Header(None, alias="X-Customer-ID"),
    service: IngestionService = Depends(get_ingestion_service)
):
    """Fetch the status of an active execution (tenant-scoped if header provided)."""
    status = await service.get_job_status(job_id, customer_id=customer_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return status

@app.get("/api/v1/tenants")
async def get_tenants(service: IngestionService = Depends(get_ingestion_service)):
    """Fetch all registered tenants/customers."""
    return await service.get_all_tenants()

@app.get("/api/v1/tenants/{customer_id}/jobs")
async def get_tenant_jobs(customer_id: str, limit: int = 20, service: IngestionService = Depends(get_ingestion_service)):
    """Fetch recent jobs for a specific tenant."""
    return await service.get_tenant_jobs(customer_id, limit)

@app.get("/api/v1/tickets/{ticket_id}/report")
async def get_ticket_report(
    ticket_id: str,
    customer_id: str = Header(None, alias="X-Customer-ID"),
    service: IngestionService = Depends(get_ingestion_service)
):
    """Fetch the generated markdown report once completed (tenant-scoped)."""
    report = await service.get_ticket_report(ticket_id, customer_id=customer_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not generated yet or ticket not found")
    return report
