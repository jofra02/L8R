from abc import ABC, abstractmethod
from typing import List, Dict, Any, Type, Optional
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

class VectorStoreInterface(ABC):
    """Abstract base class for Vector Database operations."""

    @abstractmethod
    async def ensure_collection(self, collection_name: str, vector_size: int = 1536):
        pass

    @abstractmethod
    async def add_texts(
        self, collection_name: str, texts: List[str],
        metadatas: List[Dict[str, Any]], ids: List[str],
        customer_id: str, source_type: str, run_id: Optional[str] = None,
    ):
        pass

    @abstractmethod
    async def search(
        self, collection_name: str, query_text: str, customer_id: str,
        limit: int = 5, score_threshold: float = 0.0, extra_filter: list = None,
    ) -> List[Any]:
        pass

    @abstractmethod
    async def save_evidence(self, snapshot: Any, customer_id: str, run_id: str = None):
        pass

    @abstractmethod
    async def get_similar_evidence(
        self, query: str, customer_id: str, limit: int = 5, score_threshold: float = 0.7,
    ) -> List[Any]:
        pass

    @abstractmethod
    async def save_resolved_ticket(self, ticket: Any, customer_id: str):
        pass

    @abstractmethod
    async def find_similar_cases(self, problem_description: str, customer_id: str, limit: int = 3) -> List[Any]:
        pass

    @abstractmethod
    async def save_tool_insight(self, knowledge: Any, customer_id: str = "global"):
        pass

    @abstractmethod
    async def get_tool_insights(self, tool_name: str, customer_id: str = "global", query: str = "", limit: int = 3) -> List[Any]:
        pass

    @abstractmethod
    async def save_adaptive_fix(self, tool_name: str, error_msg: str, insight: str, fix_data: Dict[str, Any], customer_id: str):
        pass

    @abstractmethod
    async def get_adaptive_fixes(self, tool_name: str, error_msg: str, customer_id: str, limit: int = 2) -> List[Any]:
        pass

    @abstractmethod
    async def index_tool(
        self, tool_name: str, description: str, args_schema_json: dict,
        server_name: str, customer_id: str,
        vendor: str = "", method: str = "", read_only: bool = True,
        category: str = "", param_count: int = 0,
    ):
        pass

    @abstractmethod
    async def search_tool_catalog(
        self, intent: str, customer_id: str, limit: int = 8,
        score_threshold: float = 0.15,
        vendor: str = None, method: str = None,
        read_only: bool = None, categories: List[str] = None,
    ) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_indexed_tool_names(self, customer_id: str) -> set:
        pass

    @abstractmethod
    async def search_knowledge_base(
        self, query: str, customer_id: str, limit: int = 3, score_threshold: float = None,
    ) -> List[Dict[str, Any]]:
        pass
