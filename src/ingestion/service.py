from sqlalchemy.ext.asyncio import AsyncSession
from src.core.models import Ticket
from src.core.orm import TicketORM
from src.ingestion.normalizers.generic import GenericNormalizer
from typing import Dict, Any, Type
import logging

logger = logging.getLogger(__name__)

class IngestionService:
    """Service to handle ticket ingestion and persistence."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.normalizer = GenericNormalizer()  # In future, use factory based on source

    async def ingest_webhook(self, source: str, payload: Dict[str, Any], customer_id: str) -> str:
        """Process a webhook payload."""
        logger.info(f"Ingesting webhook from {source} for customer {customer_id}")
        
        # 1. Normalize
        ticket: Ticket = self.normalizer.normalize(payload, source_id=f"webhook:{source}")
        
        # 2. Persist to DB
        ticket_orm = TicketORM(
            id=ticket.id,
            customer_id=customer_id,
            mode=ticket.mode,
            severity=ticket.severity,
            source=ticket.source,
            text=ticket.text,
            raw_payload=ticket.raw_payload
        )
        
        self.session.add(ticket_orm)
        await self.session.commit()
        
        # 3. Trigger Agent (Future: Push to Redis/Queue)
        logger.info(f"Ticket {ticket.id} persisted. Triggering agent workflow...")
        
        return ticket.id
