import hashlib
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional
from src.core.models import EvidenceSnapshot
import logging

logger = logging.getLogger(__name__)

class EvidenceStore:
    """Manages immutable evidence artifacts."""
    
    def __init__(self, base_path: str = "data/evidence"):
        self.base_path = base_path
        os.makedirs(self.base_path, exist_ok=True)
        
    async def save_evidence(self, tool_name: str, tool_args: Dict[str, Any], content: Any, summary: Optional[str] = None) -> EvidenceSnapshot:
        """Persist evidence and return a snapshot reference."""
        
        # 1. Serialize content
        if isinstance(content, (dict, list)):
            content_str = json.dumps(content, sort_keys=True, default=str)
        else:
            content_str = str(content)
            
        # 2. Compute hash (Content Addressable Storage)
        content_hash = hashlib.sha256(content_str.encode()).hexdigest()
        
        # 3. Save to disk (Blob Store)
        # Using hash as filename for deduplication
        file_path = os.path.join(self.base_path, f"{content_hash}.json")
        if not os.path.exists(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content_str)
                
        # 4. Create Snapshot Object
        snapshot_id = f"ev_{content_hash[:8]}"
        
        final_summary = summary or f"Output from {tool_name} ({len(content_str)} bytes)"
        
        return EvidenceSnapshot(
            id=snapshot_id,
            tool_call_id="unknown",  # To be filled by caller
            tool_name=tool_name,
            tool_args=tool_args,
            timestamp=datetime.now(),
            content_hash=content_hash,
            summary=final_summary,
            storage_ref=file_path
        )
