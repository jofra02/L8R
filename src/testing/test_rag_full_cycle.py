import asyncio
import uuid
from datetime import datetime
from src.core.models import Ticket, ResolvedTicket, ToolKnowledge
from src.core.qdrant import vector_store

async def test_rag_full_cycle():
    """
    Test the entire RAG pipeline for consistency:
    1. Tool Knowledge (Atels)
    2. Adaptive Fixes (Healer)
    3. Resolved Tickets (CBR)
    """
    
    # Generate unique test IDs
    test_run_id = str(uuid.uuid4())[:8]
    tool_name = f"test_tool_{test_run_id}"
    ticket_id = f"ticket_{test_run_id}"
    
    print(f"\n--- Starting RAG Full Cycle Test (Run ID: {test_run_id}) ---")

    try:
        # --- 1. Test Tool Knowledge ---
        print("[1/3] Testing Tool Knowledge (Atels)...")
        knowledge = ToolKnowledge(
            tool_name=tool_name,
            error_pattern="connection refused",
            insight=f"Always use port 443 for {tool_name}",
            good_example={"port": 443}
        )
        await vector_store.save_tool_insight(knowledge)
        
        # Verify
        insights = await vector_store.get_tool_insights(tool_name)
        assert len(insights) > 0, "Failed to retrieve saved tool insight"
        assert insights[0]['insight'] == knowledge.insight
        print("  -> PASS: Tool Knowledge saved & retrieved.")

        # --- 2. Test Adaptive Fixes (Healer) ---
        print("[2/3] Testing Adaptive Fixes...")
        error_msg = f"Error 500 in {tool_name}"
        fix_data = {"bad": "arg1", "good": "arg2"}
        
        await vector_store.save_adaptive_fix(
            tool_name=tool_name,
            error_msg=error_msg,
            insight="Retry with arg2",
            fix_data=fix_data
        )
        
        fixes = await vector_store.get_adaptive_fixes(tool_name, error_msg)
        assert len(fixes) > 0, "Failed to retrieve adaptive fix"
        assert fixes[0]['fix'] == fix_data
        print("  -> PASS: Adaptive Fix saved & retrieved.")

        # --- 3. Test Resolved Tickets (CBR) ---
        print("[3/3] Testing Resolved Tickets (CBR)...")
        problem = f"Cannot access server {test_run_id}"
        resolved = ResolvedTicket(
            ticket_id=ticket_id,
            problem_summary=problem,
            resolution_summary="Rebooted firewall",
            root_cause="Firmware bug",
            tools_used=[],
            steps_taken=[],
            customer_id="TEST_TENANT",
            resolved_at=datetime.now()
        )
        
        await vector_store.save_resolved_ticket(resolved)
        
        # Verify Semantic Search
        similar = await vector_store.find_similar_cases(problem, limit=1)
        assert len(similar) > 0, "Failed to find similar case"
        # similar uses return [pt.payload], so it's a dict
        assert similar[0]['ticket_id'] == ticket_id
        print("  -> PASS: Resolved Ticket indexed & semantically retrieved.")

    finally:
        # --- Cleanup ---
        print("\n--- Cleaning up Test Artifacts ---")
        pass

if __name__ == "__main__":
    asyncio.run(test_rag_full_cycle())
