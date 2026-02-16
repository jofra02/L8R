from fastapi import FastAPI, Depends, HTTPException, Query, Body, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional
from src.core.database import get_session
from src.ingestion.service import IngestionService
from src.config import settings

app = FastAPI(title=settings.APP_NAME, version="0.1.0")

# --- Dependencies ---

async def get_ingestion_service(session: AsyncSession = Depends(get_session)) -> IngestionService:
    return IngestionService(session)

# --- Endpoints ---

@app.get("/health")
async def health_check():
    """Simple health check."""
    return {"status": "ok", "app": settings.APP_NAME}

@app.post("/api/v1/webhook/{source_id}")
async def receive_webhook(
    source_id: str,
    payload: Dict[str, Any] = Body(...),
    customer_id: str = Header(..., alias="X-Customer-ID"),
    service: IngestionService = Depends(get_ingestion_service)
):
    """
    Ingest a ticket via webhook.
    Requires X-Customer-ID header for tenant isolation.
    """
    try:
        if not customer_id:
            raise HTTPException(status_code=400, detail="Missing X-Customer-ID header")
            
        ticket_id = await service.ingest_webhook(source_id, payload, customer_id)
        return {"status": "accepted", "ticket_id": ticket_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
