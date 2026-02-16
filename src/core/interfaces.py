from abc import ABC, abstractmethod
from typing import List, Dict, Any, Type
from pydantic import BaseModel
from .models import Ticket

class IngestorInterface(ABC):
    """Abstract base class for ticket ingestion sources."""
    
    @abstractmethod
    async def authenticate(self) -> bool:
        """Verify connection to the source."""
        pass
    
    @abstractmethod
    async def fetch_tickets(self, lookback_minutes: int = 60) -> List[Dict[str, Any]]:
        """Fetch raw ticket data from the source."""
        pass
    
    @abstractmethod
    def normalize(self, raw_data: Dict[str, Any]) -> Ticket:
        """Convert raw data into a standardized Ticket object."""
        pass

class MCPToolInterface(ABC):
    """Abstract base class for an MCP Tool adapter."""
    
    name: str
    description: str
    args_schema: Type[BaseModel]
    
    @abstractmethod
    async def run(self, **kwargs) -> str:
        """Execute the tool logic (read-only)."""
        pass

class CapabilityPackInterface(ABC):
    """Abstract base class for a Capability Pack (Plugin)."""
    
    id: str
    version: str
    
    @abstractmethod
    def get_tools(self) -> List[MCPToolInterface]:
        """Return a list of MCP tools provided by this pack."""
        pass
    
    @abstractmethod
    def get_playbooks(self) -> List[Dict[str, Any]]:
        """Return a list of playbook definitions (YAML dicts)."""
        pass
    
    @abstractmethod
    def get_normalizers(self) -> Dict[str, Any]:
        """Return normalization mapping logic."""
        pass
    
    @abstractmethod
    def get_hypothesis_templates(self) -> List[Dict[str, Any]]:
        """Return reasoning templates."""
        pass
