# Task: Implement Skills System for Engineer Agent

## Overview

Implement a skills system that gives the engineer agent investigation methodology and domain-specific expertise. The system combines two patterns:

- **Pattern 1 (Pre-fetch):** A base investigation skill is ALWAYS loaded into the system prompt. This skill teaches the agent HOW to work — classify tickets, build context before acting, iterate on hypotheses, produce structured findings. It applies to every ticket regardless of domain.

- **Pattern 3 (On-demand tool):** Domain-specific skills (networking, virtualization, storage, security, etc.) are available as a tool the agent can call. The agent reads the ticket, determines the domain, and loads the relevant methodology on demand. This saves context window space while giving deep domain expertise when needed.

## Architecture

```
System Prompt (always loaded):
  ├── Engineer role + identity
  ├── Base investigation skill (it-investigation-skill.md)  ← Pattern 1
  └── Available resources description (DB, RAG, MCP, skills tool)

Tools available to agent:
  ├── query_client_db(...)
  ├── search_tool_catalog(...)
  ├── search_knowledge_base(...)
  ├── execute_tool(...)
  └── load_domain_skill(domain)  ← Pattern 3 (NEW)
```

---

## Part 1: Skills File Structure

### Directory layout

```
src/
  agents/
    engineer_agent.py          # Existing agent node
    engineer_prompts.py        # Existing prompts module
    engineer_tools.py          # Existing tools module
    skills/                    # NEW directory
      __init__.py
      base_investigation.md    # Base skill — always loaded (Pattern 1)
      networking.md            # Domain skill — on demand (Pattern 3)
      virtualization.md        # Domain skill — on demand (Pattern 3)
      firewall_security.md     # Domain skill — on demand (Pattern 3)
      vpn_ipsec.md             # Domain skill — on demand (Pattern 3)
      storage.md               # Domain skill — on demand (Pattern 3)
      ... (more domains as needed)
```

### Skill file format

Each `.md` file is plain markdown. No special syntax, no frontmatter needed. The content is loaded as-is into the prompt or returned as tool output. The files already exist — use the investigation skills we've written previously as the initial content.

The `base_investigation.md` should contain the general investigation methodology:
- Ticket classification (incident, change request, review, inquiry)
- Phase-based approach (understand → build context → investigate → produce findings)
- Critical thinking rules (don't assume, always discover, follow the evidence)
- Output format templates
- Anti-patterns

The domain-specific files should contain:
- Domain-specific reasoning frameworks (e.g., OSI layer isolation for networking)
- Investigation templates with step-by-step procedures for that domain
- Common pitfalls specific to that domain
- Cross-reference guidance for tool discovery in that domain

---

## Part 2: Pattern 1 — Base Skill in System Prompt

### What to change in `engineer_prompts.py`

The `ENGINEER_SYSTEM_PROMPT` currently contains the agent's role, instructions, and output format. Modify it to INCLUDE the base investigation skill content at the end of the prompt.

### Implementation

```python
# engineer_prompts.py

from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "skills"

def _load_skill(filename: str) -> str:
    """Load a skill markdown file from the skills directory."""
    path = SKILLS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""

# Load base skill at module level (it's always needed)
_BASE_SKILL = _load_skill("base_investigation.md")

ENGINEER_SYSTEM_PROMPT = f"""
# Role
You are a Senior IT Infrastructure Engineer working on a managed services platform.
You are vendor-agnostic and domain-agnostic — you handle networking, security,
virtualization, storage, cloud, and any IT infrastructure domain.

# Your Mission
Investigate and diagnose the ticket below. Think like a senior engineer:
understand the environment, form hypotheses, gather evidence, and reach conclusions.

# Available Resources

## Client Database (DB/ORM)
Query the client database to understand the tenant's environment:
- Devices and their metadata (type, vendor, firmware, IP, role)
- Dependencies and topology (what connects to what)
- Tenant configuration and context
Use this FIRST to understand what you're working with before touching any device tools.

## Tool Catalog (RAG)
Search for available diagnostic tools. Each tool has a description, input schema
with required and optional parameters, and information about what data it returns.
Read tool descriptions carefully. Select tools that help verify your hypotheses.

## Tool Knowledge Base (RAG)
Search for vendor documentation, best practices, known issues, error code meanings,
and domain-specific knowledge.

## MCP Tool Execution
Execute tools against live devices. Every tool call requires:
- device_id: obtain this from the client database
- Tool-specific arguments: fill these from your investigation context
You have READ-ONLY access only.

## Domain Skills (load_domain_skill tool)
You have access to specialized investigation methodologies for specific IT domains.
After reading the ticket and identifying the domain (networking, firewall, vpn,
virtualization, storage, etc.), call `load_domain_skill` to load the relevant
methodology. This gives you domain-specific reasoning frameworks, step-by-step
investigation templates, and common pitfalls for that area.

**Always load the relevant domain skill before starting your investigation.**

# Investigation Methodology

{_BASE_SKILL}

# Constraints
- Read-only access only. Never attempt write/modify operations.
- Always get client context from the database before executing device tools.
- Always load the relevant domain skill before deep investigation.
- When a tool requires a specific identifier (host_id, interface_name, policy_id),
  first use a broader tool to discover what identifiers exist, then drill into
  the specific one relevant to the investigation.

# Output Format
Produce structured findings:
- Summary: one-paragraph overview of what was found
- Root Cause: what is causing the reported issue (if determinable)
- Evidence: specific tool outputs that support the conclusion
- Impact Assessment: what is affected and how severely
- Recommendations: what should be done to resolve (if applicable)
- Investigation Trail: what was checked and what was ruled out
"""
```

### Key points

- The base skill is loaded ONCE at import time — no file I/O per request.
- The base skill content is embedded directly in the system prompt string.
- It goes AFTER the resources section and BEFORE the constraints, so the agent sees the methodology right before it starts working.
- Keep the base skill concise enough to not bloat the prompt excessively. Target ~2000-3000 tokens max for the base skill. If it's longer, trim to the most critical content (phases, critical thinking rules, output format).

---

## Part 3: Pattern 3 — Domain Skills as On-Demand Tool

### What to change in `engineer_tools.py`

Add a new tool `load_domain_skill` to the list of tools returned by `create_engineer_tools()`.

### Implementation

```python
# In engineer_tools.py

from pathlib import Path
from langchain_core.tools import tool

SKILLS_DIR = Path(__file__).parent / "skills"

# Map of domain keywords to skill filenames
DOMAIN_SKILL_MAP = {
    "networking": "networking.md",
    "routing": "networking.md",
    "switching": "networking.md",
    "interfaces": "networking.md",
    "bgp": "networking.md",
    "ospf": "networking.md",
    "dns": "networking.md",
    "dhcp": "networking.md",
    "qos": "networking.md",
    "firewall": "firewall_security.md",
    "security": "firewall_security.md",
    "nat": "firewall_security.md",
    "policies": "firewall_security.md",
    "ids": "firewall_security.md",
    "ips": "firewall_security.md",
    "vpn": "vpn_ipsec.md",
    "ipsec": "vpn_ipsec.md",
    "tunnel": "vpn_ipsec.md",
    "ssl_vpn": "vpn_ipsec.md",
    "virtualization": "virtualization.md",
    "hypervisor": "virtualization.md",
    "esxi": "virtualization.md",
    "vcenter": "virtualization.md",
    "vm": "virtualization.md",
    "ha_cluster": "virtualization.md",
    "storage": "storage.md",
    "san": "storage.md",
    "nas": "storage.md",
    "vsan": "storage.md",
    "lun": "storage.md",
    "backup": "storage.md",
}

def _get_available_domains() -> list[str]:
    """Return list of available domain skill files."""
    return [f.stem for f in SKILLS_DIR.glob("*.md") if f.stem != "base_investigation"]


def create_load_domain_skill_tool():
    """Create the domain skill loading tool."""

    @tool
    def load_domain_skill(domain: str) -> str:
        """Load the investigation methodology for a specific IT domain.

        Call this BEFORE starting deep investigation to get domain-specific
        reasoning frameworks, step-by-step investigation templates, and
        common pitfalls for the area you're investigating.

        Args:
            domain: The IT domain to load methodology for.
                    Examples: "networking", "routing", "firewall", "vpn",
                    "ipsec", "virtualization", "vcenter", "storage", "san",
                    "security", "nat", "bgp", "ospf", "dns", "dhcp"

        Returns:
            The domain-specific investigation methodology as markdown text.
            If the domain is not recognized, returns available domains.
        """
        # Normalize input
        domain_lower = domain.lower().strip().replace(" ", "_").replace("-", "_")

        # Direct filename match first
        direct_path = SKILLS_DIR / f"{domain_lower}.md"
        if direct_path.exists():
            return direct_path.read_text(encoding="utf-8")

        # Try keyword mapping
        if domain_lower in DOMAIN_SKILL_MAP:
            skill_file = SKILLS_DIR / DOMAIN_SKILL_MAP[domain_lower]
            if skill_file.exists():
                return skill_file.read_text(encoding="utf-8")

        # Not found — return helpful message with available domains
        available = _get_available_domains()
        return (
            f"No specific skill found for domain '{domain}'. "
            f"Available domain skills: {', '.join(available)}. "
            f"Try one of these, or proceed with the base investigation methodology "
            f"already in your system prompt."
        )

    return load_domain_skill
```

### Wire it into `create_engineer_tools()`

In the existing `create_engineer_tools()` function, add the skill tool to the tools list:

```python
def create_engineer_tools(customer_id, run_id, ticket_id, max_tool_calls):
    # ... existing tool creation code ...

    # Create domain skill tool
    domain_skill_tool = create_load_domain_skill_tool()

    # Add to tools list alongside existing tools
    tools = [
        query_client_db_tool,
        search_tool_catalog_tool,
        search_knowledge_base_tool,
        execute_tool_tool,
        domain_skill_tool,          # ← ADD THIS
    ]

    return tools, tool_state
```

---

## Part 4: Expected Agent Behavior After Implementation

With both patterns in place, the agent's natural flow should look like this:

```
1. Agent receives ticket: "En fgt_casa, necesito enviar tráfico a 100.64.120.0/27 por IPSEC"

2. Agent reads the base methodology (already in system prompt):
   → Classifies as CHANGE REQUEST
   → Knows it needs to: understand environment → discover current state → analyze gap → produce recommendations

3. Agent calls load_domain_skill("networking")
   → Gets the networking investigation skill
   → Now has: layer isolation framework, effective routing table methodology,
     traffic flow analysis, dependency chains, VPN/IPSEC investigation templates

4. Agent calls query_client_db to get device context for "fgt_casa"
   → Gets device_id, vendor (FortiGate), firmware, topology

5. Agent calls search_tool_catalog for "list interfaces fortigate"
   → Finds available interface listing tools

6. Agent calls execute_tool(device_id=..., tool="get_system_interface")
   → Discovers all interfaces, identifies IPSEC tunnel interfaces

7. Agent calls search_tool_catalog for "routing table fortigate"
   → Finds routing table tools

8. Agent calls execute_tool(device_id=..., tool="get_router_static")
   → Gets current routing configuration
   → Also gets effective routing table to check if 100.64.120.0/27 already has a route

9. Agent analyzes: which tunnel reaches that subnet? Are selectors correct?
   Are there conflicting routes? Is the tunnel up?

10. Agent produces findings with full context, recommendations, and risk assessment
```

The key difference from before: steps 2-3 give the agent a METHODOLOGY. Without the skills, the agent might jump from step 1 directly to step 10 and say "add a static route" without checking anything. With the skills, it follows a systematic process.

---

## Part 5: Managing Skill Content

### Token budget considerations

- **Base skill (Pattern 1):** Always loaded, so keep it tight. Target 2000-3000 tokens. Focus on: phases of investigation, critical thinking rules, output format. Remove verbose examples — those go in domain skills.
- **Domain skills (Pattern 3):** Loaded on demand, can be more detailed. Target 3000-5000 tokens each. Include: domain-specific frameworks, step-by-step templates, worked examples, common pitfalls.
- **Total budget:** With a 128k-200k context window, 5000-8000 tokens of skills is a small fraction. This is worth the investment.

### Adding new domain skills

To add a new domain (e.g., `high_availability.md`):

1. Create the `.md` file in `src/agents/skills/`
2. Add keyword mappings in `DOMAIN_SKILL_MAP` in `engineer_tools.py`
3. That's it — the tool automatically discovers `.md` files in the skills directory

### Updating skills without redeployment

Because skills are loaded from files at runtime (Pattern 3) or at import time (Pattern 1):
- **Domain skills (Pattern 3):** File changes take effect on the next tool call. No restart needed.
- **Base skill (Pattern 1):** File is read at module import time. Requires process restart to pick up changes. If you want hot-reload, change `_BASE_SKILL` from a module-level constant to a function that reads the file each time `ENGINEER_SYSTEM_PROMPT` is constructed. Trade-off: file I/O per request vs. hot-reload capability.

For hot-reload of the base skill:

```python
def build_system_prompt() -> str:
    """Build the system prompt with fresh base skill content."""
    base_skill = _load_skill("base_investigation.md")
    return PROMPT_TEMPLATE.format(base_skill=base_skill)
```

Then in `engineer_agent.py`, call `build_system_prompt()` instead of using the constant.

---

## Part 6: Skill Content — Initial Files to Create

### `base_investigation.md`

Use the content from the previously created `it-investigation-skill.md`. Trim it to the essentials:
- Phase 1: Understand the Request (ticket classification)
- Phase 2: Build Context (what to discover before investigating)
- Phase 3: Investigate (reasoning loop for each ticket type)
- Phase 4: Critical Thinking Rules (the 6 rules)
- Phase 5: Output Structure (templates for each ticket type)

Remove the worked example and the investigation templates by topic — those belong in the domain skills.

### `networking.md`

Use the content from the previously created `network-engineering-skill.md`. This includes:
- Framework 1: Layer Isolation (OSI/TCP model, bottom-up, top-down, divide-and-conquer)
- Framework 2: Effective State vs Configured State
- Framework 3: Traffic Flow Analysis (forward + return path)
- Framework 4: Dependency Chain Analysis
- Framework 5: The Effective Routing Table
- Investigation Methodology step-by-step
- Common Pitfalls
- Cross-reference: concepts to tool discovery

### `firewall_security.md`, `vpn_ipsec.md`, `virtualization.md`, `storage.md`

These need to be created following the same structure as `networking.md`:
- Domain-specific reasoning frameworks
- Step-by-step investigation templates
- Dependency chains for the domain
- Common pitfalls
- Tool discovery guidance

For now, create stub files with a basic structure and a TODO comment. The networking skill serves as the template for how thorough each domain skill should be. We'll fill them in iteratively.

Stub format:

```markdown
# Skill: [Domain] Investigation Methodology

## Purpose
[One sentence describing what this skill covers]

## TODO
This skill needs to be expanded following the pattern established in `networking.md`.
For now, use the base investigation methodology from the system prompt and apply
general IT troubleshooting principles to this domain.

## Key Concepts for [Domain]
- [List 3-5 most important things to check in this domain]
- [Common patterns]
- [Typical dependencies]
```

---

## Part 7: Verification

After implementation, verify:

1. **Base skill loads correctly:**
   - Print or log `ENGINEER_SYSTEM_PROMPT` and confirm the base methodology is present
   - Check token count of the full prompt — should be reasonable (under 5000 tokens for the prompt itself)

2. **Domain skill tool works:**
   - Call `load_domain_skill("networking")` directly and verify it returns the full networking skill
   - Call `load_domain_skill("routing")` and verify it maps to the networking skill via `DOMAIN_SKILL_MAP`
   - Call `load_domain_skill("nonexistent")` and verify it returns available domains
   - Call `load_domain_skill("NETWORKING")` and verify case normalization works

3. **Agent uses skills in practice:**
   - Run a test ticket and check logs/traces for:
     - `load_domain_skill` being called early in the investigation
     - Agent following the methodology (building context before executing specific tools)
     - Output matching the structured format from the skill

4. **No regression:**
   - Run existing test tickets and verify the agent still produces quality results
   - Check that the additional prompt content doesn't push the context window over limits