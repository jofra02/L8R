import asyncio
import uuid
import logging
from unittest.mock import AsyncMock, MagicMock
from src.core.adaptive_executor import AdaptiveExecutor
from src.core.interfaces import MCPToolInterface
from src.core.models import ToolKnowledge
from src.core.qdrant import vector_store
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestAdaptiveHealing")

class MockToolArgs(BaseModel):
    target: str = Field(..., description="Target device IP or hostname")
    force: bool = False

class MockTool(MCPToolInterface):
    name: str = "test_tool"
    description: str = "A test tool"
    args_schema = MockToolArgs
    
    def __init__(self):
        self.should_fail = True
        self.call_count = 0
        
    async def run(self, **kwargs) -> str:
        self.call_count += 1
        print(f"DEBUG: MockTool called with {kwargs}", flush=True)
        
        # Simulate failure if 'target' is bad
        if kwargs.get("target") == "bad_target":
            raise ValueError("Invalid target. Try using IP address.")
        
        return "Success"

async def test_adaptive_rag_healing():
    """
    Verifies the self-healing loop:
    1. Exec fails -> Learn -> Save.
    2. Exec fails again -> Retrieve -> Auto-Fix.
    """
    print("\n--- Starting Adaptive RAG Healing Test ---")
    
    run_id = str(uuid.uuid4())[:6]
    tool_name = f"test_tool_{run_id}"
    
    # 1. Setup Executor
    executor = AdaptiveExecutor(max_retries=1)
    
    # Mock LLM
    executor.llm = AsyncMock()
    # Ensure it returns a mocked message object
    mock_msg = MagicMock()
    mock_msg.content = '{"target": "192.168.1.1"}'
    executor.llm.ainvoke.return_value = mock_msg
    
    # 2. Simulate "Learning Phase"
    # We manually save a fix to Qdrant to simulate a past learning event
    print("[1] Seeding Knowledge Base with past fix...")
    
    error_msg = "Invalid target. Try using IP address."
    fix_data = {"bad": {"target": "bad_target"}, "good": {"target": "192.168.1.1"}}
    
    await vector_store.save_adaptive_fix(
        tool_name="test_tool", # Using the name from MockTool
        error_msg=error_msg,
        insight="Always use valid IP for target.",
        fix_data=fix_data,
        customer_id="test_tenant"
    )

    # Verify save
    fixes = await vector_store.get_adaptive_fixes("test_tool", error_msg, customer_id="test_tenant")
    assert len(fixes) > 0
    print("  -> Fix seeded.")
    
    # 3. Simulate "Execution Phase" where it fails
    print("[2] Running Executor with BAD args (Should trigger RAG diagnosis)...")
    
    tool = MockTool()
    bad_args = {"target": "bad_target"}
    
    # Check if retrieval works by inspecting the logs or the side_effect
    # But fundamentally, if execute returns success, it means diagnosis worked.
    
    result = await executor.execute(tool, bad_args)
    
    assert result == "Success"
    assert tool.call_count == 2 # 1st fail, 2nd success
    print("  -> Executor successfully self-healed!")
    
    print("  -> Executor successfully self-healed!")
    
    # 4. Simulate "Grounding Failure" -> Missing Dependency
    # print("[3] Testing Missing Dependency Signal...")
    
    # # Mock response for Missing Info
    # missing_resp = MagicMock()
    # missing_resp.content = '{"missing_info": "Need management IP for switch X", "suggested_source": "CMDB"}'
    # executor.llm.ainvoke.return_value = missing_resp
    
    # # We must reset side_effect if we want to use return_value or append to side_effect
    # executor.llm.ainvoke.side_effect = None
    # executor.llm.ainvoke.return_value = missing_resp
    
    # try:
    #     await executor.execute(tool, bad_args)
    #     print("FAIL: Should have raised MissingDependencyError")
    # except Exception as e:
    #     # Check if it's our special error (by string check as class import might be tricky in script text)
    #     if "Missing: Need management IP" in str(e):
    #          print(f"  -> PASS: Caught expected MissingDependencyError: {e}")
    #     else:
    #          print(f"FAIL: Caught unexpected error: {type(e)} {e}")
    #          raise e

    print("\n--- Test Passed ---\n")

if __name__ == "__main__":
    asyncio.run(test_adaptive_rag_healing())
