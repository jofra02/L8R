import asyncio
import logging
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.interfaces import IngestorInterface
from src.core.database import async_session_factory
from src.core.orm import TicketORM
from src.ingestion.service import IngestionService
from sqlalchemy import select

logger = logging.getLogger(__name__)

class PollerService:
    """Manages periodic polling of external sources."""
    
    def __init__(self, ingestors: List[IngestorInterface]):
        self.ingestors = ingestors
        self.running = False
        
    async def start(self, interval: int = 60, customer_id: str = "default_customer"):
        """Start the polling loop."""
        self.running = True
        logger.info(f"Starting poller with {len(self.ingestors)} sources. Interval: {interval}s")
        
        while self.running:
            try:
                async with async_session_factory() as session:
                    ingestion_service = IngestionService(session)
                    await self._poll_all(ingestion_service, customer_id)
            except Exception as e:
                logger.error(f"Error in polling loop: {e}", exc_info=True)
            
            await asyncio.sleep(interval)
            
    async def stop(self):
        """Stop the polling loop."""
        self.running = False

    async def _poll_all(self, service: IngestionService, customer_id: str):
        """Poll all ingestors."""
        for ingestor in self.ingestors:
            try:
                # 1. Authenticate (fail fast)
                if not await ingestor.authenticate():
                    logger.warning(f"Authentication failed for {ingestor.__class__.__name__}")
                    continue
                
                # 2. Fetch
                raw_tickets = await ingestor.fetch_tickets()
                
                for raw in raw_tickets:
                    await self._process_ticket(ingestor, raw, service, customer_id)
                    
            except Exception as e:
                logger.error(f"Error polling {ingestor.__class__.__name__}: {e}")

    async def _process_ticket(self, ingestor: IngestorInterface, raw: Dict[str, Any], service: IngestionService, customer_id: str):
        """Process a single raw ticket."""
        try:
            # Normalize to get ID
            ticket = ingestor.normalize(raw)
            
            # Check for duplication (Dedup)
            # Efficient query to check existence
            stmt = select(TicketORM.id).where(TicketORM.id == ticket.id, TicketORM.customer_id == customer_id)
            result = await service.session.execute(stmt)
            if result.scalar_one_or_none():
                logger.debug(f"Ticket {ticket.id} already exists. Skipping.")
                return

            # Ingest
            # Re-normalize inside service? No, service expects payload or ticket.
            # Let's use the service logic but we already normalized.
            # We can persist directly or refactor service.
            # Ideally, service handles the full flow.
            # Let's call a method on service that accepts the Ticket object?
            # Or just recreate the flow.
            
            from src.core.orm import TicketORM
            ticket_orm = TicketORM(
                id=ticket.id,
                customer_id=customer_id,
                mode=ticket.mode,
                severity=ticket.severity,
                source=ticket.source,
                text=ticket.text,
                raw_payload=ticket.raw_payload
            )
            service.session.add(ticket_orm)
            await service.session.commit()
            logger.info(f"Polled new ticket {ticket.id} from {ticket.source}")
            
        except Exception as e:
            logger.error(f"Error processing polled ticket: {e}")
