> Historical design spec — implemented. This document proposed the single Engineer ReAct agent that replaced the 13-agent pipeline and is now the shipped architecture. Current docs: [Architecture Overview](../../architecture/overview.md), [Engineer Agent](../../agents/engineer.md).

# Redesign: Minimal Agent Architecture

## The Problem With Many Agents

Every agent boundary is a **lossy compression point**. When Agent A hands off to Agent B:
- Agent A's full reasoning gets summarized into a handoff message
- Agent B rebuilds context from that summary — nuance is lost
- The chain of inference that connected "this ARP entry looks wrong" to "that's why the tunnel is flapping" gets severed
- By agent 5 or 6, the system is operating on summaries of summaries

The LLM's core value is **inference** — connecting dots, forming hypotheses, adjusting based on evidence. That capacity lives in the context window. Every agent boundary fragments that context window.

**Principle: One brain, many hands.** The LLM is the brain. Tools are the hands. You don't need 20 brains — you need 1 brain with access to all the hands it needs.

---

## Architecture: 2 Agents Total

### Agent 1: The Engineer (core agent — where all intelligence lives)

**Identity:**
```
You are a Senior IT Infrastructure Engineer. You are vendor-agnostic and domain-agnostic.
You troubleshoot, investigate, diagnose, and review architecture and implementation
across all IT domains: networking, security, virtualization, storage, cloud, and beyond.
```

**What it has access to:**

| Resource | What it provides | How the agent uses it |
|---|---|---|
| **DB/ORM** | Client/tenant context — devices, dependencies, topology, metadata, tenant config | Agent queries this FIRST to understand the environment: what devices exist, how they're connected, what the architecture looks like. This is the "who is this client and what do they have" step |
| **RAG — tool_catalog** | Index of all available tools with descriptions, schemas, parameter details | Agent searches this to find what tools are available for the task at hand. Instead of a tool_selector pipeline, the agent itself reads tool descriptions and decides what to use |
| **RAG — tool_knowledge** | Documentation, best practices, known issues, vendor-specific knowledge | Agent queries this for domain expertise: "how does FortiGate handle IPSec phase2 rekeying", "what does this error code mean", "what's the correct way to check OSPF neighbors on this platform" |
| **MCP Server** | Executable tools (currently FortiGate, will expand). Each tool requires device_id + tool-specific args | Agent executes tools against actual devices. Read-only tools only — the user/service account has read-only permissions. Agent passes device_id (obtained from DB context) + tool args |

**What it does — single continuous reasoning chain:**

```
1. READ THE TICKET
   Understand what the client is reporting or requesting.

2. GET CLIENT CONTEXT (DB/ORM)
   Query the database to understand:
   - What devices/components does this tenant have?
   - How are they connected/dependent on each other?
   - What's the topology/architecture?
   - Any relevant metadata (firmware versions, licenses, contracts)?
   
   This gives the agent the "map of the terrain" before investigating.

3. FORM HYPOTHESES
   Based on the ticket + client context, reason about:
   - What could be causing this?
   - What are the most likely failure points?
   - What do I need to verify?
   
   This is pure LLM inference — no tools, no agents, just thinking.

4. FIND RELEVANT TOOLS (RAG — tool_catalog)
   Search the tool catalog for tools that can verify the hypotheses.
   The agent reads the tool schemas and descriptions and selects
   which tools to use and in what order.
   
   Apply discovery-first logic naturally:
   - "I need to check the interfaces, but I don't know which interface
     is the problem. Let me first list all interfaces, then drill into
     the one that looks wrong."
   
   The agent does this because it's what a senior engineer would do.
   Not because a pipeline forces it. The LLM naturally understands
   "I need to know what exists before I can inspect something specific."

5. EXECUTE TOOLS (MCP Server)
   Run the selected tools against the actual devices.
   Use device_id from DB context + tool args.
   Read the output. Analyze it. Connect it to the hypotheses.

6. ITERATE
   Based on tool output:
   - Confirm or discard hypotheses
   - Form new hypotheses based on what was found
   - Query additional tools if needed
   - Dig deeper into anomalies
   
   This loop continues until the agent has enough evidence
   to reach a conclusion. The agent decides when it has enough —
   not a pipeline, not a step counter.

7. PRODUCE FINDINGS
   Structured output with:
   - What was found
   - Root cause analysis (if determinable)
   - Evidence (tool outputs that support the conclusion)
   - Recommendations
   - What was checked and ruled out
```

**Key point:** Steps 3-6 are a LOOP, not a sequence. The agent may go back to the DB for more context mid-investigation. It may search for different tools after initial findings change the direction. It may form entirely new hypotheses. This is how a real engineer works — and it only works if everything stays in ONE context window.

**What it does NOT do:**
- It does NOT make changes to devices (read-only)
- It does NOT execute remediation
- It does NOT approve changes

---

### Agent 2: The Executor (only if/when you need write operations)

**This agent only exists if the platform needs to execute changes.** If the current scope is investigation/diagnosis only, you don't need this agent at all.

**Identity:**
```
You are an IT Operations Executor. You receive a specific, pre-approved action plan
from the investigation phase. Your job is to execute the prescribed changes safely,
verify the result, and report back. You do NOT investigate or diagnose — that was
already done. You execute exactly what was approved.
```

**What it receives:**
- The approved action plan from Agent 1's findings (reviewed and approved by a human or approval workflow)
- Device context (device_id, connection details from DB)
- The specific tools to use and the specific arguments (already determined)

**What it has access to:**
- **MCP Server** with write-enabled tools (different permission level than Agent 1)
- **DB/ORM** for device context only (not for investigation)

**What it does:**
```
1. Receive approved action plan
2. Validate pre-conditions (verify current state matches expectations)
3. Execute the prescribed changes
4. Verify post-conditions (confirm the change had the expected effect)
5. Report results (success/failure, before/after state)
6. Rollback if post-conditions fail (if rollback plan was provided)
```

**Why this is a separate agent:**
- **Security boundary** — different permission levels (read-only vs read-write)
- **Audit trail** — clear separation between "what was diagnosed" and "what was changed"
- **Approval gate** — a human (or approval system) sits between Agent 1 and Agent 2
- **Scope limitation** — this agent deliberately has NO investigative capability. It can't decide to "also fix this other thing while I'm here." It does exactly what was approved, nothing more.

**This is NOT a reasoning boundary — it's a permission boundary.** The intelligence already happened in Agent 1. Agent 2 is deliberately narrow.

---

## What Replaces the 20 Agents

| Old (many agents) | New (2 agents) | Why it's better |
|---|---|---|
| Intent classifier agent | Agent 1 reads the ticket and understands intent naturally | LLMs understand intent natively — you don't need a separate classifier |
| Tool selector agent | Agent 1 searches tool_catalog RAG and selects tools itself | The engineer picks their own tools based on what they're investigating |
| Tool binder agent | Agent 1 reads the tool schema and passes the right args | An engineer who understands the tool description can fill in the parameters |
| Prerequisite resolver | Agent 1 naturally runs discovery tools first | A senior engineer doesn't need a pipeline to tell them "list first, then get detail" |
| Evidence collector agent | Agent 1 collects evidence as part of investigation | Investigation and evidence collection are the same activity |
| Evaluation/scoring agent | Agent 1 evaluates its own findings as it goes | An engineer doesn't need a separate person to tell them if their finding is relevant |
| Report writer agent | Agent 1 produces findings as its conclusion | The person who investigated writes the report — they have all the context |
| Executor agent | Agent 2 (only for write operations) | This is the only justified separation — it's a permission boundary, not a reasoning one |

---

## System Prompt Structure for Agent 1

```markdown
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
Use this FIRST to understand what you're working with before touching any tools.

## Tool Catalog (RAG)
Search for available diagnostic tools. Each tool has:
- A description of what it does
- An input schema with required and optional parameters
- Information about what data it returns
Read tool descriptions carefully. Select tools that help verify your hypotheses.
Remember: start broad (list/overview tools), then drill into specifics.

## Tool Knowledge Base (RAG)
Search for vendor documentation, best practices, known issues, error code meanings,
and domain-specific knowledge. Use this when you need expertise about how a specific
technology works or what a specific output means.

## MCP Tool Execution
Execute tools against live devices. Every tool call requires:
- device_id: obtain this from the client database (you know which device to target)
- Tool-specific arguments: fill these from your investigation context

You have READ-ONLY access. You can query, list, get, show, check — but you cannot
modify, configure, update, or delete anything.

# How to Work

1. Read the ticket. Understand what the client is experiencing or requesting.
2. Query the database for client/tenant context. Understand the environment.
3. Think about what could be going on. Form hypotheses.
4. Find and execute tools to verify or discard each hypothesis.
5. Iterate — follow the evidence. If findings point somewhere unexpected, follow that trail.
6. When you have enough evidence, produce your findings with root cause analysis and recommendations.Maybe the ticket is just for checking investigating the current implementation or specific config, not just troubleshooting issues.

Do NOT rush to tools before understanding the environment.
Do NOT stop at the first finding — verify it, and check for related issues.
Do NOT assume — if you're unsure about something, query for it.

# Constraints
- Read-only access only. Never attempt write/modify operations.
- Always get client context from the database before executing tools.
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
```

---

## Implementation Notes

### Context Window Management
One agent doing everything means the context window fills up. Strategies:
- **Summarize tool outputs inline** — after the agent reads a tool output, it should extract the relevant facts and not carry the full raw output forward. The system can automatically truncate large tool responses after the agent has processed them.
- **Structured fact accumulation** — as the agent discovers facts (device IDs, interface names, status values), store them in a structured facts section that persists clearly in context. This is more token-efficient than re-reading raw tool output.
- **Compaction checkpoints** — for very long investigations, implement a checkpoint where the agent summarizes findings so far, compacts context, and continues. But this should be rare — most investigations should fit in one context window.

### Tool Execution Guardrails
Even though the architecture is "let the LLM think freely," add guardrails:
- **Max tool calls per investigation** — prevent infinite loops (e.g., cap at 25-30 tool executions)
- **Read-only enforcement** — at the MCP server level, not just prompt level. The service account literally cannot write.
- **Device scope** — the agent can only target devices belonging to the tenant from the ticket. Enforce this at the MCP server / API gateway level.
- **Timeout** — total investigation time cap

### RAG Query Strategy
The agent needs to query RAG effectively:
- **tool_catalog**: search by domain/category + what the agent is trying to do.
- **specific_product/appliance_knowledge**: search when the agent encounters something it needs expertise on. Example: "FortiGate OSPF neighbor state is Init" → finds documentation explaining OSPF states and what Init means

Consider giving the agent explicit query tools:
```
search_tool_catalog(query: str) → returns matching tools with full schemas
search_knowledge_base(query: str) → returns relevant documentation/knowledge
query_client_db(query: str) → returns tenant/device/topology context
execute_tool(device_id: str, tool_name: str, args: dict) → executes MCP tool
```

These 4 "meta-tools" are all Agent 1 needs to interact with the entire platform.

### When to Add Agent 2
Don't build Agent 2 until you actually need write operations. Start with Agent 1 (investigation only) and prove the architecture. When write operations are needed:
1. Agent 1 produces findings + recommended actions
2. Human or approval system reviews and approves
3. Agent 2 receives the approved action plan and executes
4. Agent 2 reports results back

### Migration Path from Current Architecture
You don't have to delete everything at once:
1. Build Agent 1 with access to DB + RAG + MCP
2. Test it on real tickets alongside the current pipeline
3. Compare quality of investigation: does one agent with full context outperform the pipeline?
4. Gradually retire the specialized agents as Agent 1 proves it handles their responsibilities
5. Keep metrics: investigation quality, time to resolution, number of tool calls, accuracy of findings

### Model Selection
Agent 1 should use the most capable model available (Opus or equivalent). This is the one place where model quality matters enormously — the entire value of the system is in this agent's reasoning. Do not try to save costs by using a smaller model for the core reasoning agent. Use smaller models only for clearly mechanical tasks (if any remain).