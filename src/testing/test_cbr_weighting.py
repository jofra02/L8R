import asyncio
import uuid
import logging
from datetime import datetime
from src.core.models import Ticket, Plan, PlanStep
from src.core.qdrant import vector_store
from src.indexing.ticket_indexer import TicketIndexer
from src.retrieval.case_retriever import CaseRetriever

# Setup simple logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestCBR")

async def test_cbr_logic():
    """
    Verifies:
    1. Exclusion: 'unresolved' tickets are NOT indexed/retrieved.
    2. Weighting: 'resolved' (score 10) ranks higher than 'workaround' (score 5).
    """
    print("\n--- Starting CBR Weighting & Exclusion Test ---")
    
    run_id = str(uuid.uuid4())[:6]
    indexer = TicketIndexer(vector_store)
    retriever = CaseRetriever(vector_store)
    
    # Shared problem text to ensure they are all "semantic matches"
    # We want to test that metadata/scoring drives the ranking, not just vector distance.
    problem_text = f"Application crashing with memory error code 0x{run_id}"
    
    # --- Data Prep ---
    
    # Case A: Unresolved (Should be ignored)
    ticket_a = Ticket(
        id=f"t_unresolved_{run_id}", mode="incident", text=problem_text, 
        severity="medium", source="test"
    )
    plan_a = Plan(proposed_changes=[PlanStep(step_id="1", description="Tried reboot", tool="reboot", args={}, expected_outcome="")])
    
    # Case B: Workaround (Score 5)
    ticket_b = Ticket(
        id=f"t_workaround_{run_id}", mode="incident", text=problem_text, 
        severity="medium", source="test"
    )
    plan_b = Plan(proposed_changes=[PlanStep(step_id="1", description="Restart service regularly", tool="restart", args={}, expected_outcome="")])
    
    # Case C: Resolved (Score 10)
    ticket_c = Ticket(
        id=f"t_resolved_{run_id}", mode="incident", text=problem_text, 
        severity="medium", source="test"
    )
    plan_c = Plan(proposed_changes=[PlanStep(step_id="1", description="Patch binary", tool="patch", args={}, expected_outcome="")])

    # --- 1. Indexing ---
    
    print(f"\n[1] Indexing 3 cases for problem: '{problem_text}'...")
    
    # A: unresovled
    await indexer.index_resolved_case(
        ticket_a, plan_a, final_answer="Could not fix.", customer_id="TEST", 
        resolution_status="unresolved"
    )
    
    # B: workaround
    await indexer.index_resolved_case(
        ticket_b, plan_b, final_answer="Script to restart.", customer_id="TEST", 
        resolution_status="workaround"
    )
    
    # C: resolved
    await indexer.index_resolved_case(
        ticket_c, plan_c, final_answer="Applied patch.", customer_id="TEST", 
        resolution_status="resolved"
    )
    
    # --- 2. Retrieval ---
    
    print("\n[2] Retrieving similar cases...")
    # Query with the exact same text
    query_ticket = Ticket(id="query", mode="incident", text=problem_text, severity="high", source="test")
    
    results = await retriever.retrieve_similar_cases(query_ticket, limit=5)
    
    print(f"\n[3] Results Found: {len(results)}")
    for i, res in enumerate(results):
        print(f"  Rank {i+1}: ID={res.ticket_id}, Status={res.resolution_status}, Score={res.score}")
        
    # --- 3. Assertions ---
    
    ids_found = [r.ticket_id for r in results]
    
    # Exclusion check
    if ticket_a.id in ids_found:
        print("FAIL: Unresolved ticket was retrieved!")
        exit(1)
    else:
        print("PASS: Unresolved ticket excluded.")
        
    # Ranking check
    # We expect 'resolved' (C) to be before 'workaround' (B)
    # Note: Vector score might be identical since text is identical. 
    # So our sort by 'score' should determine order.
    
    if ticket_c.id in ids_found and ticket_b.id in ids_found:
        idx_c = ids_found.index(ticket_c.id)
        idx_b = ids_found.index(ticket_b.id)
        
        if idx_c < idx_b:
            print("PASS: Resolved case ranked higher than Workaround.")
        else:
            print(f"FAIL: Ranking incorrect. Resolved at {idx_c}, Workaround at {idx_b}")
            exit(1)
    else:
        print("FAIL: Not all expected tickets found.")
        print(f"Expected: {ticket_c.id}, {ticket_b.id}")
        print(f"Found: {ids_found}")
        exit(1)

if __name__ == "__main__":
    asyncio.run(test_cbr_logic())
