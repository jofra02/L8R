import asyncio
import argparse
import sys
import logging
import json
from src.testing.mocks import get_base_state, get_response_ready_state, mock_component
from src.agents.response import response_agent_node
from src.agents.evidence_collector import evidence_collector_node
# Import other agents as needed

# Configure Logging to stdout
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

AGENTS = {
    "response": response_agent_node,
    "evidence_collector": evidence_collector_node
}

async def run_agent(agent_name: str, ticket_text: str = None):
    if agent_name not in AGENTS:
        logger.error(f"Unknown agent: {agent_name}. Available: {list(AGENTS.keys())}")
        sys.exit(1)
        
    logger.info(f"Setting up environment for {agent_name}...")
    
    # Select appropriate mock state based on agent
    if agent_name == "response":
        state = get_response_ready_state()
    else:
        state = get_base_state()
        
    # Override ticket text if provided
    if ticket_text:
        state["ticket"].text = ticket_text
        
    # For Evidence Collector, ensure we have a component
    if agent_name == "evidence_collector" and not state["components"]:
        state["components"] = [mock_component("fgt_demo", "firewall")]

    logger.info(f"Running agent node: {agent_name}")
    try:
        result = await AGENTS[agent_name](state)
        print("\n" + "="*50)
        print(f"AGENT OUTPUT ({agent_name}):")
        print(json.dumps(result, indent=2, default=str))
        print("="*50 + "\n")
    except Exception as e:
        logger.error(f"Agent execution failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a specific agent in isolation with mock data.")
    parser.add_argument("agent", help="Name of the agent to run (e.g., 'response')")
    parser.add_argument("--ticket", help="Override ticket text", default=None)
    
    args = parser.parse_args()
    
    asyncio.run(run_agent(args.agent, args.ticket))
