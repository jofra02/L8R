from typing import Any, Dict, List, Optional

from src.core.models import GlobalState, Component, ClientContext
from src.core.llm import LLMFactory
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)

class ComponentList(BaseModel):
    components: List[Component] = Field(description="List of potential components involved")

async def mapper_agent_node(state: GlobalState) -> Dict[str, Any]:
    """
    LangGraph node: Maps ticket text to components.
    identifies devices, IP addresses, services, etc.
    Post-processes LLM output to reconcile IDs against the real inventory.
    """
    ticket = state["ticket"]
    context = state.get("client_context")
    logger.info(f"Mapper Agent: Scoping ticket {ticket.id}")

    llm = LLMFactory.get_model_for_agent("mapper")
    parser = PydanticOutputParser(pydantic_object=ComponentList)

    # Context summary for the LLM
    inventory_summary = "No inventory available."
    if context and context.inventory:
        if len(context.inventory) <= 50:
             items_str = "\n".join([f"- {c.id}: {c.ref} ({c.vendor} {c.role})" for c in context.inventory])
             inventory_summary = f"Customer has {len(context.inventory)} assets:\n{items_str}"
        else:
             inventory_summary = f"Customer has {len(context.inventory)} assets in inventory."

    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "You are an expert IT Support / Incident Engineer. "
            "Analyze the ticket and identify technical components (devices, IPs, URLs, services, users, applications, databases, clusters, containers, APIs, storage, endpoints). "
            "When a component matches an inventory item, use that item's exact `id` value as the component `id`. "
            "Only generate a new id for components not present in the inventory. "
            "Infer the 'vendor' if explicitly mentioned or implied by the context."
        )),
        ("user", "Inventory:\n{inventory}\n\nTicket: {text}\n\n{format_instructions}")
    ])

    chain = prompt | llm | parser

    try:
        result = await chain.ainvoke({
            "inventory": inventory_summary,
            "text": ticket.text,
            "format_instructions": parser.get_format_instructions()
        })

        # Reconcile LLM-generated IDs against the real inventory
        reconciled = _reconcile_with_inventory(result.components, context)

        logger.info(f"Mapper result: Found {len(reconciled)} components.")
        return {"components": reconciled, "case_status": "triaged"}

    except Exception as e:
        logger.error(f"Mapper failed: {e}")
        return {"components": [], "missing_info": ["mapper_error"], "case_status": "triaged"}



def _reconcile_with_inventory(
    components: List[Component],
    context: Optional[ClientContext],
) -> List[Component]:
    """
    Deterministic post-processing: correct LLM-generated component IDs
    against the real inventory.  Handles prefixes (comp_), suffixes,
    partial matches and ref-based matching.
    """
    if not context or not context.inventory:
        return components

    # Build lookup tables from inventory
    inv_by_id: Dict[str, Any] = {}      # exact id -> inventory item
    inv_by_ref: Dict[str, Any] = {}     # lowercase ref -> inventory item
    for item in context.inventory:
        inv_by_id[item.id.lower()] = item
        inv_by_ref[item.ref.lower()] = item

    reconciled: List[Component] = []
    for comp in components:
        original_id = comp.id
        lower_id = original_id.lower()

        # 1. Already correct
        if lower_id in inv_by_id:
            # Ensure casing matches the canonical ID
            canonical = inv_by_id[lower_id]
            comp = _apply_inventory(comp, canonical)
            reconciled.append(comp)
            continue

        # 2. Strip common LLM-generated prefixes (comp_, component_, asset_)
        matched = _try_strip_prefix(lower_id, inv_by_id)
        if matched:
            logger.info(f"Mapper reconcile: '{original_id}' -> '{matched.id}' (prefix strip)")
            comp = _apply_inventory(comp, matched)
            reconciled.append(comp)
            continue

        # 3. Check if the generated id is a substring of an inventory id or vice-versa
        matched = _try_substring_match(lower_id, inv_by_id)
        if matched:
            logger.info(f"Mapper reconcile: '{original_id}' -> '{matched.id}' (substring)")
            comp = _apply_inventory(comp, matched)
            reconciled.append(comp)
            continue

        # 4. Match by ref (the LLM might have used the human-readable name as id)
        if lower_id in inv_by_ref:
            matched_item = inv_by_ref[lower_id]
            logger.info(f"Mapper reconcile: '{original_id}' -> '{matched_item.id}' (ref match)")
            comp = _apply_inventory(comp, matched_item)
            reconciled.append(comp)
            continue

        # 5. No match — keep as-is (unknown component not in inventory)
        reconciled.append(comp)

    return reconciled


def _try_strip_prefix(lower_id: str, inv_by_id: Dict[str, Any]) -> Optional[Any]:
    """Try removing common prefixes the LLM might have added."""
    prefixes = ("comp_", "component_", "asset_", "device_", "host_")
    for prefix in prefixes:
        if lower_id.startswith(prefix):
            stripped = lower_id[len(prefix):]
            if stripped in inv_by_id:
                return inv_by_id[stripped]
    return None


def _try_substring_match(lower_id: str, inv_by_id: Dict[str, Any]) -> Optional[Any]:
    """Check if the generated id contains an inventory id or vice-versa."""
    for inv_id, item in inv_by_id.items():
        if inv_id in lower_id or lower_id in inv_id:
            return item
    return None


def _apply_inventory(comp: Component, inv_item: Any) -> Component:
    """Override component fields with canonical inventory values."""
    return comp.model_copy(update={
        "id": inv_item.id,
        "ref": inv_item.ref if not comp.ref else comp.ref,
        "vendor": inv_item.vendor or comp.vendor,
    })
