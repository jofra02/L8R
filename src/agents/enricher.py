from typing import Any, Dict
from src.core.models import GlobalState
from src.core.llm import LLMFactory
from langchain_core.messages import SystemMessage, HumanMessage
import logging
import json

logger = logging.getLogger(__name__)

async def enricher_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Enriches facts with extra context by synthesizing evidence.
    """
    evidence_refs = state.get("evidence_refs", [])
    facts = state.get("facts", {})
    
    logger.info(f"Enricher: Processing {len(evidence_refs)} evidence items.")
    
    # Identify evidence that hasn't been synthesized into facts yet
    # We use a simple heuristic: if evidence ID isn't in a tracker fact, process it
    processed_evidence_ids = facts.get("_processed_evidence_ids", [])
    new_evidence = [e for e in evidence_refs if e.id not in processed_evidence_ids]
    
    if not new_evidence:
        logger.info("Enricher: No new evidence to synthesize.")
        return {}

    logger.info(f"Enricher: Synthesizing {len(new_evidence)} new evidence items into facts.")
    llm = LLMFactory.get_model_for_agent("enricher")
    
    enriched_facts = facts.copy()
    
    for ref in new_evidence:
        # We need the full content. Load from EvidenceStore disk path.
        try:
            with open(ref.storage_ref, "r", encoding="utf-8") as f:
                raw_text = f.read()
                try:
                    raw_content = json.loads(raw_text)
                except json.JSONDecodeError:
                    raw_content = {"raw_text": raw_text}
        except Exception as e:
            logger.warning(f"Enricher: Could not load file {ref.storage_ref}: {e}")
            raw_content = {"summary": ref.summary}
            
        from src.utils.json_compressor import compress_json_payload
        compressed_evidence = compress_json_payload(raw_content)
        evidence_str = json.dumps(compressed_evidence, indent=2)
        
        prompt = f"""
        Extract key technical facts from the following evidence snippet gathered during an IT incident investigation.
        Focus on concrete values: IP addresses, error codes, statuses, latency, configuration settings.
        
        Evidence Tool: {ref.tool_name}
        Evidence Summary: {ref.summary}
        Evidence Content (Compressed): 
        {evidence_str}
        
        Return ONLY a JSON dictionary of key-value pairs representing the discrete facts found.
        Example: {{"interface_wan1_status": "down", "dns_latency_ms": 150}}
        """
        
        try:
             response = await llm.ainvoke([
                 SystemMessage(content="You are a data extraction specialist. Output only valid JSON."),
                 HumanMessage(content=prompt)
             ])
             extracted_json = response.content.strip().replace("```json", "").replace("```", "")
             extracted_facts = json.loads(extracted_json)
             
             for k, v in extracted_facts.items():
                 # Avoid overwriting existing important facts blindly, or append them
                 if k not in enriched_facts:
                     enriched_facts[k] = v
                 else:
                     # If it exists, we might want to version it or just overwrite if newer evidence
                     enriched_facts[k] = v 
             
             logger.info(f"Enricher: Extracted {len(extracted_facts)} facts from evidence {ref.id[:8]}")
             processed_evidence_ids.append(ref.id)
             
        except Exception as e:
             logger.warning(f"Enricher: Failed to extract facts from {ref.id[:8]}: {e}")
             # Still mark as processed so we don't retry forever
             processed_evidence_ids.append(ref.id)
             
    enriched_facts["_processed_evidence_ids"] = processed_evidence_ids
            
    return {"facts": enriched_facts}
