from typing import List, Dict, Any, Type
from pydantic import BaseModel, Field
from src.core.interfaces import CapabilityPackInterface, MCPToolInterface
import yaml
import os

class GenericCapabilityPack(CapabilityPackInterface):
    """
    Standard capability pack for basic network diagnostics.
    """
    id = "generic"
    version = "1.0.0"
    
    def __init__(self):
        self._tools = []
        self._load_resources()

    def _load_resources(self):
        # In a real impl, read from yaml files in the package
        self._playbooks = []
        self._hypotheses = []
        
        # Mocking for now
        self._playbooks.append({
            "id": "check_connectivity",
            "name": "Basic Connectivity Check",
            "steps": []
        })
        
        self._hypotheses.append({
            "id": "network_down",
            "template": "Target {target} is unreachable via ICMP."
        })

    def get_tools(self) -> List[MCPToolInterface]:
        return self._tools
    
    def get_playbooks(self) -> List[Dict[str, Any]]:
        return self._playbooks
    
    def get_normalizers(self) -> Dict[str, Any]:
        return {}
        
    def get_hypothesis_templates(self) -> List[Dict[str, Any]]:
        return self._hypotheses
