from typing import List, Dict, Any, Type
import asyncio
import logging
from src.core.interfaces import IngestorInterface
from src.core.models import Ticket
from src.ingestion.normalizers.generic import GenericNormalizer

logger = logging.getLogger(__name__)

class MockIngestor(IngestorInterface):
    """Simulates an external ticketing system."""
    
    def __init__(self, name: str = "mock-source"):
        self.name = name
        self.normalizer = GenericNormalizer()
        
    async def authenticate(self) -> bool:
        return True
    
    async def fetch_tickets(self, lookback_minutes: int = 60) -> List[Dict[str, Any]]:
        """Return a dummy ticket."""
        logger.info(f"Checking for new tickets in {self.name}...")
        # Simulate check delay
        await asyncio.sleep(0.1)
        
        # Return a dummy ticket occasionally?
        # For now, just return empty to avoid spamming unless testing
        return []
    
    def normalize(self, raw_data: Dict[str, Any]) -> Ticket:
        return self.normalizer.normalize(raw_data, source_id=f"poller:{self.name}")
