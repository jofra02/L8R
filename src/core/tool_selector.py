"""
Centralized tool selection pipeline: Intent → Retrieval → Evaluation → Arg Binding.

Replaces duplicated selection logic in evidence_collector and investigator with
a single, reasoned, per-tool evaluation approach.
"""

from typing import Any, Dict, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
import json
import logging

from src.core.models import (
    Component, Hypothesis, ToolIntent, ToolCandidate,
    ToolEvaluation, ToolSelection, ToolSelectionContext,
)
from src.core.registry import CapabilityRegistry
from src.core.llm import LLMFactory

logger = logging.getLogger(__name__)


class ToolSelector:
    """
    Four-phase tool selection pipeline:
      1. Intent generation (LLM) — short keyword queries
      2. Semantic retrieval (Qdrant) — candidate tools per intent
      3. Per-tool evaluation (LLM, batched ≤5) — relevant/not + reasoning
      4. Argument binding (LLM) — configure args for approved tools only
    """

    def __init__(self, customer_id: str):
        self.customer_id = customer_id
        self.llm = LLMFactory.get_model_for_agent("evidence_collector")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def select_tools(
        self,
        context: ToolSelectionContext,
        max_intents: int = 3,
        max_candidates_per_intent: int = 10,
        max_tools: int = 8,
    ) -> List[ToolSelection]:
        """Full pipeline: intents → retrieval → evaluation → arg binding."""
        # Phase 1
        intents = await self.generate_intents(context, max_intents)
        if not intents:
            logger.warning("ToolSelector: No intents generated.")
            return []

        # Phase 2
        candidates = await self.retrieve_candidates(intents, context, max_candidates_per_intent)
        if not candidates:
            logger.warning("ToolSelector: Semantic search returned 0 candidates. Trying brute-force fallback.")
            candidates = self._get_brute_force_candidates(context)
        if not candidates:
            logger.warning("ToolSelector: No candidates found (including brute-force).")
            return []

        # Phase 3
        evaluations = await self.evaluate_candidates(candidates, context)
        approved = [e for e in evaluations if e.relevant]
        approved.sort(key=lambda e: e.priority)
        approved = approved[:max_tools]

        logger.info(
            f"ToolSelector: {len(evaluations)} evaluated, "
            f"{len([e for e in evaluations if e.relevant])} approved, "
            f"{len(approved)} after max_tools clip"
        )

        if not approved:
            logger.info("ToolSelector: No candidates approved by evaluation.")
            return []

        # Phase 4
        selections = await self.bind_arguments(approved, candidates, context)
        return selections

    # ------------------------------------------------------------------
    # Phase 1: Intent Generation
    # ------------------------------------------------------------------

    async def generate_intents(
        self, context: ToolSelectionContext, max_intents: int = 3,
    ) -> List[ToolIntent]:
        """LLM generates keyword search queries based on mode."""
        prompt = self._build_intent_prompt(context, max_intents)

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="You are a tool-search specialist. Output short keyword queries for finding IT diagnostic tools."),
                HumanMessage(content=prompt),
            ])
            parsed = json.loads(
                response.content.strip().replace("```json", "").replace("```", "")
            )
            raw_intents = parsed.get("intents", [])
            if isinstance(raw_intents, str):
                raw_intents = [raw_intents]
            raw_intents = raw_intents[:max_intents]

            return [ToolIntent(query=q) for q in raw_intents if q]

        except Exception as e:
            logger.warning(f"ToolSelector: Intent generation failed: {e}")
            return self._fallback_intents(context)

    # ------------------------------------------------------------------
    # Phase 2: Semantic Retrieval
    # ------------------------------------------------------------------

    async def retrieve_candidates(
        self, intents: List[ToolIntent], context: ToolSelectionContext,
        limit_per_intent: int = 10,
    ) -> List[ToolCandidate]:
        """Semantic search per intent, merge + deduplicate. Applies vendor filter from context."""
        from src.core.qdrant import vector_store

        # Extract vendor filter from context
        vendor_filter = None
        if context.component and context.component.vendor:
            vendor_filter = context.component.vendor.lower()
        elif context.source_component and context.source_component.vendor:
            vendor_filter = context.source_component.vendor.lower()

        seen: Dict[str, ToolCandidate] = {}

        for intent in intents:
            try:
                payloads = await vector_store.search_tool_catalog(
                    intent=intent.query,
                    customer_id=self.customer_id,
                    limit=limit_per_intent,
                    vendor=vendor_filter,
                    read_only=True,
                )
                for payload in payloads:
                    t_name = payload.get("tool_name")
                    if not t_name or t_name in seen:
                        continue
                    tool = CapabilityRegistry.get_tool(t_name)
                    if not tool:
                        continue
                    if not CapabilityRegistry._is_safe(t_name):
                        continue
                    seen[t_name] = ToolCandidate(
                        tool_name=t_name,
                        description=tool.description or t_name,
                        args_schema=(
                            tool.args_schema.model_json_schema()
                            if tool.args_schema else {}
                        ),
                        search_score=payload.get("score", 0.0),
                        source_intent=intent.query,
                        catalog_context=payload.get("page_content", ""),
                        vendor=payload.get("vendor", ""),
                        method=payload.get("method", ""),
                        read_only=payload.get("read_only", "true") == "true",
                        category=payload.get("category", ""),
                        param_count=payload.get("param_count", 0),
                    )
            except Exception as e:
                logger.warning(f"ToolSelector: Semantic search failed for '{intent.query[:50]}': {e}")

        # Vendor fallback: retry without vendor filter if no results
        if not seen and vendor_filter:
            logger.info(f"ToolSelector: No vendor-specific results for '{vendor_filter}'. Retrying without vendor filter.")
            for intent in intents:
                try:
                    payloads = await vector_store.search_tool_catalog(
                        intent=intent.query,
                        customer_id=self.customer_id,
                        limit=limit_per_intent,
                        read_only=True,
                    )
                    for payload in payloads:
                        t_name = payload.get("tool_name")
                        if not t_name or t_name in seen:
                            continue
                        tool = CapabilityRegistry.get_tool(t_name)
                        if not tool:
                            continue
                        if not CapabilityRegistry._is_safe(t_name):
                            continue
                        seen[t_name] = ToolCandidate(
                            tool_name=t_name,
                            description=tool.description or t_name,
                            args_schema=(
                                tool.args_schema.model_json_schema()
                                if tool.args_schema else {}
                            ),
                            search_score=payload.get("score", 0.0),
                            source_intent=intent.query,
                            catalog_context=payload.get("page_content", ""),
                            vendor=payload.get("vendor", ""),
                            method=payload.get("method", ""),
                            read_only=payload.get("read_only", "true") == "true",
                            category=payload.get("category", ""),
                            param_count=payload.get("param_count", 0),
                        )
                except Exception as e:
                    logger.warning(f"ToolSelector: Vendor fallback search failed for '{intent.query[:50]}': {e}")

        candidates = list(seen.values())
        logger.info(f"ToolSelector: {len(candidates)} unique candidates from {len(intents)} intents.")
        return candidates

    # ------------------------------------------------------------------
    # Phase 3: Per-Tool Evaluation (batched)
    # ------------------------------------------------------------------

    async def evaluate_candidates(
        self,
        candidates: List[ToolCandidate],
        context: ToolSelectionContext,
    ) -> List[ToolEvaluation]:
        """LLM evaluates candidates in batches of ≤5."""
        all_evaluations: List[ToolEvaluation] = []
        batch_size = 5

        for i in range(0, len(candidates), batch_size):
            batch = candidates[i : i + batch_size]
            evals = await self._evaluate_batch(batch, context)
            all_evaluations.extend(evals)

        return all_evaluations

    async def _evaluate_batch(
        self,
        batch: List[ToolCandidate],
        context: ToolSelectionContext,
    ) -> List[ToolEvaluation]:
        """Evaluate a single batch (≤5 candidates)."""
        # Build context section
        if context.mode == "investigation" and context.hypothesis:
            goal_section = (
                f"Hypothesis: \"{context.hypothesis.summary}\"\n"
                f"Rationale: {context.hypothesis.rationale}\n"
            )
        elif context.mode == "relational" and context.source_component and context.target_component:
            goal_section = (
                f"Source: {context.source_component.id} (Role: {context.source_component.role})\n"
                f"Target: {context.target_component.id} (Role: {context.target_component.role})\n"
                f"Goal: Verify relationship/reachability between source and target.\n"
            )
        else:
            comp_str = ""
            if context.component:
                comp_str = f"Component: {context.component.id} (Role: {context.component.role}, Vendor: {context.component.vendor or 'unknown'})\n"
            goal_section = comp_str

        components_str = ", ".join(
            f"{c.id} ({c.role})" for c in (context.components or [])
        )
        facts_keys = ", ".join(list(context.facts.keys())[:20]) if context.facts else "none"

        # Build candidate descriptions with full schema + catalog context
        candidate_lines = []
        for idx, c in enumerate(batch, 1):
            schema_str = json.dumps(c.args_schema, indent=2) if c.args_schema else "none"
            context_line = f"\n   Catalog detail: {c.catalog_context}" if c.catalog_context else ""
            candidate_lines.append(
                f"{idx}. {c.tool_name} (score: {c.search_score:.2f}, vendor: {c.vendor or 'generic'}, "
                f"method: {c.method}, category: {c.category}): {c.description}{context_line}\n"
                f"   Schema: {schema_str}"
            )
        candidates_block = "\n".join(candidate_lines)

        evidence_section = ""
        if context.evidence_summaries:
            evidence_section = f"\nPrevious evidence collected:\n{context.evidence_summaries}\n"

        prompt = f"""You are evaluating diagnostic tools for an IT support investigation.

INVESTIGATION GOAL:
Ticket: "{context.ticket_text}"
{goal_section}
AVAILABLE CONTEXT:
- Components: {components_str}
- Known facts: {facts_keys}
{evidence_section}
CANDIDATE TOOLS TO EVALUATE:
{candidates_block}

For EACH tool, answer:
1. Does the tool's PURPOSE match what we're investigating?
2. Can we provide the REQUIRED parameters from available context (components, facts)?
3. Will the tool's OUTPUT contribute useful diagnostic data?
4. CONFIGURATION-FIRST: Prefer config-reading tools over live traffic tools.
5. If a tool was already executed (check previous evidence), mark as not relevant.

Return ONLY a JSON list (one entry per tool, same order):
[
    {{"tool_name": "...", "relevant": true, "reasoning": "1-2 sentences", "priority": 1}},
    ...
]

Priority: 1=most critical, 5=nice-to-have. Only assign priority if relevant=true.
Irrelevant tools: set priority=0.
"""

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="You are an expert IT diagnostic tool evaluator. Assess each tool independently."),
                HumanMessage(content=prompt),
            ])
            raw = json.loads(
                response.content.strip().replace("```json", "").replace("```", "")
            )
            if not isinstance(raw, list):
                raw = [raw]

            evaluations = []
            for entry in raw:
                evaluations.append(ToolEvaluation(
                    tool_name=entry.get("tool_name", ""),
                    relevant=bool(entry.get("relevant", False)),
                    reasoning=entry.get("reasoning", ""),
                    priority=int(entry.get("priority", 0)),
                ))
            return evaluations

        except Exception as e:
            logger.warning(f"ToolSelector: Batch evaluation failed: {e}. Approving all candidates as fallback.")
            return [
                ToolEvaluation(
                    tool_name=c.tool_name,
                    relevant=True,
                    reasoning="Evaluation failed — approved by fallback.",
                    priority=idx + 1,
                )
                for idx, c in enumerate(batch)
            ]

    # ------------------------------------------------------------------
    # Phase 4: Argument Binding
    # ------------------------------------------------------------------

    async def bind_arguments(
        self,
        approved: List[ToolEvaluation],
        candidates: List[ToolCandidate],
        context: ToolSelectionContext,
    ) -> List[ToolSelection]:
        """LLM constructs args only for approved tools."""
        # Build candidate lookup
        candidate_map = {c.tool_name: c for c in candidates}

        # Fetch insights for approved tools
        from src.core.qdrant import vector_store
        insights_text = ""
        try:
            combined = []
            for ev in approved:
                insights = await vector_store.get_tool_insights(ev.tool_name, limit=1)
                for ins in insights:
                    combined.append(f"For {ev.tool_name}: {ins.get('insight')}")
            if combined:
                insights_text = "LEARNED BEST PRACTICES:\n" + "\n".join(combined)
        except Exception as e:
            logger.warning(f"ToolSelector: Failed to fetch insights: {e}")

        # Build component context for arg binding (full metadata)
        if context.mode == "relational" and context.source_component and context.target_component:
            comp_section = (
                f"Source component:\n{self._format_component_for_binding(context.source_component)}\n\n"
                f"Destination component:\n{self._format_component_for_binding(context.target_component)}"
            )
        elif context.component:
            comp_section = f"Component:\n{self._format_component_for_binding(context.component)}"
        else:
            comp_section = "No specific component."

        # Build tool descriptions with full schema
        tool_lines = []
        for idx, ev in enumerate(approved, 1):
            cand = candidate_map.get(ev.tool_name)
            schema_str = json.dumps(cand.args_schema, indent=2) if cand else "{}"
            tool_lines.append(
                f"{idx}. {ev.tool_name}: {cand.description if cand else 'N/A'}\n"
                f"   Schema: {schema_str}"
            )
        tools_block = "\n".join(tool_lines)

        prompt = f"""{comp_section}

APPROVED TOOLS (configure arguments for each):
{tools_block}

{insights_text}

GUIDELINES:
1. For 'device', 'host', 'hostname' args: use the component ID of the executor-role component.
2. For target/address parameters: match the component ID or metadata values to the parameter's schema type and description. If the schema expects a single host and the available value is an aggregate (e.g. subnet, group, cluster), derive an appropriate singular value.
3. Use ALL metadata fields to fill matching parameters.
4. Analyze Schema: distinguish mandatory vs optional parameters.
5. ANTI-HALLUCINATION: Do NOT invent parameters. If a mandatory param has no value from context, SKIP that tool entirely.
6. READ-ONLY only. No modify/delete/configure actions.

Return ONLY a JSON list:
[
    {{"name": "tool_name_1", "args": {{...}}}},
    {{"name": "tool_name_2", "args": {{...}}}}
]
If you must skip a tool due to missing mandatory params, omit it from the list.
"""

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="You are an expert IT automation engineer. Configure tool arguments precisely."),
                HumanMessage(content=prompt),
            ])
            raw = json.loads(
                response.content.strip().replace("```json", "").replace("```", "")
            )
            if isinstance(raw, dict):
                raw = [raw]

            # Map back to ToolSelection with evaluation attached
            eval_map = {ev.tool_name: ev for ev in approved}
            selections = []
            for entry in raw:
                name = entry.get("name", "")
                args = entry.get("args", {})
                ev = eval_map.get(name)
                if not ev:
                    continue
                selections.append(ToolSelection(
                    name=name,
                    args=args,
                    evaluation=ev,
                ))

            logger.info(f"ToolSelector: {len(selections)} tools with bound arguments.")
            return selections

        except Exception as e:
            logger.error(f"ToolSelector: Arg binding failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_component_for_binding(comp: Component) -> str:
        """Format a component with all metadata for LLM arg binding."""
        lines = [
            f"  ID: {comp.id}",
            f"  Role: {comp.role}",
            f"  Vendor: {comp.vendor or 'unknown'}",
        ]
        if comp.ref and comp.ref != comp.id:
            lines.append(f"  Ref: {comp.ref}")
        if comp.metadata:
            for k, v in comp.metadata.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Brute-force fallback
    # ------------------------------------------------------------------

    def _get_brute_force_candidates(
        self, context: ToolSelectionContext,
    ) -> List[ToolCandidate]:
        """Fallback: safe read-only tools filtered by vendor/role."""
        from src.core.registry import _extract_tool_metadata

        comp = context.component or context.source_component
        if not comp:
            return []

        all_tools = CapabilityRegistry.list_tools()
        vendor_kw = comp.vendor.lower() if comp.vendor else ""
        candidates = []

        for t in all_tools:
            schema = t.args_schema.model_json_schema() if t.args_schema else {}
            meta = _extract_tool_metadata(t.name, t.description or "", schema, getattr(t, 'server_name', 'builtin'))

            if not meta["read_only"]:
                continue
            if vendor_kw and meta["vendor"] and meta["vendor"] != vendor_kw:
                continue

            name = t.name.lower()
            if any(k in name for k in ["health", "status", "info", "system", "summary", "overview"]):
                candidates.append(ToolCandidate(
                    tool_name=t.name,
                    description=t.description or t.name,
                    args_schema=schema,
                    search_score=0.0,
                    source_intent="brute_force_fallback",
                    vendor=meta["vendor"],
                    method=meta["method"],
                    read_only=meta["read_only"],
                    category=meta["category"],
                    param_count=meta["param_count"],
                ))

        return candidates[:10]

    # ------------------------------------------------------------------
    # Intent prompt builders
    # ------------------------------------------------------------------

    def _build_intent_prompt(self, context: ToolSelectionContext, max_intents: int) -> str:
        """Build the intent generation prompt based on mode."""
        if context.mode == "investigation":
            return self._build_investigation_intent_prompt(context, max_intents)
        elif context.mode == "relational":
            return self._build_relational_intent_prompt(context, max_intents)
        else:
            return self._build_evidence_intent_prompt(context, max_intents)

    def _build_evidence_intent_prompt(self, context: ToolSelectionContext, max_intents: int) -> str:
        comp = context.component
        vendor_ctx = f"Vendor: {comp.vendor}" if comp and comp.vendor else "Vendor: Unknown"
        comp_id = comp.id if comp else "unknown"
        comp_role = comp.role if comp else "unknown"
        all_components_str = ", ".join(f"{c.id} ({c.role})" for c in context.components) if context.components else "none"

        path_section = ""
        if context.path_context:
            path_section = f"\nAlso address these evidence gaps:\n{context.path_context}\n"

        return f"""Ticket: "{context.ticket_text}"
Component: {comp_id} (Role: {comp_role}). {vendor_ctx}
All components: {all_components_str}

Task: Generate 1-{max_intents} SHORT tool-search queries to find the right diagnostic tools for this component.

RULES:
1. Each query must be 2-6 words — like a search engine query, NOT a sentence.
2. Do NOT include vendor or product names — vendor filtering is applied automatically. Focus on WHAT the tool does.
3. Focus on the CATEGORY of tool needed (routing, policy, interface, performance, logs, database, deployment, container, api, authentication, storage, backup, etc.).
4. Do NOT include IPs, subnets, or ticket-specific details — those are for tool arguments, not tool search.
5. Do NOT write sentences or descriptions — write search keywords only.
6. CONFIGURATION-FIRST: Prefer tools that read existing configuration (routes, policies, rules, definitions) over live traffic tools (debug flows, captures, sniffers, sessions).
{path_section}
EXAMPLES (do not copy literally, adapt to the ticket and vendor):
{{"intents": ["firewall routing table", "firewall policy rules"]}}
{{"intents": ["database replication status", "connection pool metrics"]}}
{{"intents": ["kubernetes pod health", "container resource usage"]}}

Return ONLY a JSON object:
{{"intents": ["query 1", "query 2"]}}
"""

    def _build_investigation_intent_prompt(self, context: ToolSelectionContext, max_intents: int) -> str:
        hyp = context.hypothesis
        components_str = ", ".join(
            f"{c.id} ({c.role})" for c in context.components
        ) if context.components else "none"
        facts_keys = ", ".join(list(context.facts.keys())[:15]) if context.facts else "none"

        evidence_section = ""
        if context.evidence_summaries:
            evidence_section = f"\nEvidence collected so far:\n{context.evidence_summaries}\n"

        return f"""Hypothesis: "{hyp.summary if hyp else 'unknown'}"
Rationale: {hyp.rationale if hyp else 'N/A'}
Components: {components_str}
Facts collected: {facts_keys}
{evidence_section}
Task: Generate 1-{max_intents} SHORT tool-search queries (2-6 words each) to find tools
that verify or disprove this hypothesis.

RULES:
1. Each query must be 2-6 words — keyword-style, NOT a sentence.
2. Do NOT include vendor or product names — vendor filtering is applied automatically.
3. Focus on category of diagnostic tool needed.
4. CONFIGURATION-FIRST: Prefer config-reading tools over live traffic tools.
5. Do NOT include IPs or ticket-specific details.

Return ONLY a JSON object:
{{"intents": ["query 1", "query 2"]}}
"""

    def _build_relational_intent_prompt(self, context: ToolSelectionContext, max_intents: int) -> str:
        src = context.source_component
        dst = context.target_component
        all_str = ", ".join(f"{c.id} ({c.role})" for c in context.components) if context.components else "none"

        return f"""Ticket: "{context.ticket_text}"
Source component: {src.id if src else 'unknown'} (Role: {src.role if src else 'unknown'}, Vendor: {src.vendor or 'unknown' if src else 'unknown'})
Destination component: {dst.id if dst else 'unknown'} (Role: {dst.role if dst else 'unknown'}, Vendor: {dst.vendor or 'unknown' if dst else 'unknown'})
All components: {all_str}

Task: Generate 1-{max_intents} SHORT tool-search queries to find tools that check the RELATIONSHIP
or REACHABILITY between source and destination.

RULES:
1. Each query must be 2-6 words — keyword-style, NOT a sentence.
2. Do NOT include vendor or product names — vendor filtering is applied automatically.
3. Focus on relational diagnostics: route lookup, policy check, NAT mapping, path trace, connectivity.
4. CONFIGURATION-FIRST: Prefer config-based tools (routing table, policy rules) over live traffic tools.
5. Do NOT include IPs or ticket-specific details.

Return ONLY a JSON object:
{{"intents": ["query 1", "query 2"]}}
"""

    # ------------------------------------------------------------------
    # Fallback intents
    # ------------------------------------------------------------------

    def _fallback_intents(self, context: ToolSelectionContext) -> List[ToolIntent]:
        """Produce basic intents when LLM generation fails."""
        if context.mode == "relational":
            return [
                ToolIntent(query="route lookup"),
                ToolIntent(query="policy check"),
            ]
        elif context.mode == "investigation" and context.hypothesis:
            return [
                ToolIntent(query="system status health"),
                ToolIntent(query="configuration check"),
            ]
        else:
            comp = context.component
            role = comp.role if comp else "system"
            return [
                ToolIntent(query=f"{role} status"),
                ToolIntent(query=f"{role} configuration"),
            ]
