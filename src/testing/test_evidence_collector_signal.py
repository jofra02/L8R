import asyncio
from unittest.mock import AsyncMock, MagicMock
from src.agents.evidence_collector import evidence_collector_node
from src.core.models import GlobalState, Component
from src.core.adaptive_executor import MissingDependencyError

# Mock dependencies
from src.core.registry import CapabilityRegistry
from src.core.llm import LLMFactory

async def test_evidence_collector_missing_info():
    print("\n--- Testing Evidence Collector Missing Info Handling ---")
    
    # 1. Setup Mock State
    comp = Component(id="subnet_123", role="unknown", vendor="generic")
    state = {
        "ticket": MagicMock(text="Test Ticket"),
        "components": [comp],
        "evidence_refs": []
    }
    
    # 2. Mock LLM for Tool Selection
    mock_llm = AsyncMock()
    # Return one tool: "ping"
    mock_llm.ainvoke.return_value = MagicMock(content='[{"name": "ping", "args": {"target": "subnet_123"}}]')
    LLMFactory.get_fast_llm = MagicMock(return_value=mock_llm)
    
    # 3. Mock Registry to return a tool
    mock_tool = MagicMock()
    mock_tool.name = "ping"
    mock_tool.args_schema = None 
    # Important: The AdaptiveExecutor will call tool.run()
    # We want tool.run() to fail, triggering diagnosis
    mock_tool.run = AsyncMock(side_effect=ValueError("Invalid Target"))
    
    CapabilityRegistry.get_tool = MagicMock(return_value=mock_tool)
    CapabilityRegistry._tools = {"ping": mock_tool}
    
    # 4. Mock AdaptiveExecutor inside evidence_collector
    # This is tricky because it's instantiated inside the function.
    # We can mock the class in the module.
    
    # Actually, let's rely on the real AdaptiveExecutor logic but mock ITS LLM calls
    # OR simpler: Mock the 'execute' method of AdaptiveExecutor to raise MissingDependencyError directly
    
    with unittest.mock.patch('src.agents.evidence_collector.AdaptiveExecutor') as MockExec:
        instance = MockExec.return_value
        instance.execute = AsyncMock(side_effect=MissingDependencyError("Need IP", "CMDB"))
        
        # Run logic
        result = await evidence_collector_node(state)
        
        print(f"Result: {result}")
        
        missing = result.get("missing_info", [])
        assert len(missing) == 1
        assert missing[0]["description"] == "Need IP"
        assert missing[0]["source"] == "CMDB"
        print("PASS: Missing Info correctly captured.")

import unittest.mock
if __name__ == "__main__":
    asyncio.run(test_evidence_collector_missing_info())
