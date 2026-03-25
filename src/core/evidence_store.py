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

    def __init__(self, base_path: str = "data/evidence", customer_id: str = "unknown", run_id: str = None, ticket_id: str = None):
        self.customer_id = customer_id
        self.run_id = run_id
        self.ticket_id = ticket_id
        # Namespace by tenant to isolate evidence on disk
        self.base_path = os.path.join(base_path, customer_id)
        os.makedirs(self.base_path, exist_ok=True)

    async def save_evidence(self, tool_name: str, tool_args: Dict[str, Any], content: Any, summary: Optional[str] = None) -> EvidenceSnapshot:
        """Persist evidence and return a snapshot reference."""
        
        # 1. Serialize content & Sanitize
        if isinstance(content, (dict, list)):
            content_str = json.dumps(content, sort_keys=True, default=str)
        elif content is None:
            content_str = "No Output"
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
        
        # 5. Smart Summary Extraction (Improved for MCP JSON tools)
        final_summary = summary
        if not final_summary:
            # If content is short, use it as summary
            if len(content_str) < 200:
                final_summary = content_str
            else:
                 # Try to extract "Success/Fail" from dict
                if isinstance(content, dict):
                    if "error" in content:
                        final_summary = f"Error: {content['error']}"
                    elif "output" in content:
                        # Some tools wrap everything in 'output'
                        out = content["output"]
                        if isinstance(out, dict) and "results" in out:
                             results = out["results"]
                             if isinstance(results, list):
                                 if not results:
                                     final_summary = "Success (Empty results list)"
                                 else:
                                     # Show first item briefly
                                     final_summary = f"Success ({len(results)} items). First item: {str(results[0])[:150]}..."
                             else:
                                 final_summary = str(results)[:200]
                        else:
                             final_summary = str(out)[:200]
                    # Fortinet / Default MCP JSON struct usually has 'results' at root or under 'response'
                    elif "results" in content:
                        res = content["results"]
                        if isinstance(res, list):
                            if not res:
                                final_summary = "Success (Empty results)"
                            else:
                                final_summary = f"Found {len(res)} items. Example: {str(res[0])[:150]}..."
                        else:
                            final_summary = str(res)[:200]
                    else:
                        final_summary = f"Output from {tool_name} ({len(content_str)} bytes). Keys: {list(content.keys())}"
                else:
                    final_summary = f"Output from {tool_name} ({len(content_str)} bytes)"

        snapshot = EvidenceSnapshot(
            id=snapshot_id,
            tool_call_id="unknown",  # To be filled by caller
            tool_name=tool_name,
            tool_args=tool_args,
            timestamp=datetime.now(),
            content_hash=content_hash,
            summary=final_summary,
            storage_ref=file_path
        )
        
        # 6. Async Indexing (Fire & Forget logic or Await?)
        # For data integrity, we await it here.
        try:
            from src.core.qdrant import vector_store
            await vector_store.save_evidence(snapshot, customer_id=self.customer_id, run_id=self.run_id)
        except Exception as e:
            # Don't fail the whole tool execution if indexing fails, but log it.
            logger.error(f"EvidenceStore: Failed to index evidence {snapshot_id}: {e}")

        # 7. Persist to PostgreSQL (EvidenceRefORM) for API queries
        if self.ticket_id:
            try:
                from src.core.database import async_session_factory
                from src.core.orm import EvidenceRefORM
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                async with async_session_factory() as session:
                    stmt = pg_insert(EvidenceRefORM).values(
                        id=snapshot.id,
                        ticket_id=self.ticket_id,
                        customer_id=self.customer_id,
                        tool_name=snapshot.tool_name,
                        content_hash=snapshot.content_hash,
                        storage_ref=snapshot.storage_ref,
                        summary=snapshot.summary,
                    ).on_conflict_do_nothing(index_elements=["id"])
                    await session.execute(stmt)
                    await session.commit()
            except Exception as e:
                logger.error(f"EvidenceStore: Failed to persist EvidenceRefORM {snapshot_id}: {e}")

        return snapshot
