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
from src.core.tool_categories import get_categories_prompt_block, get_related_categories, get_all_category_slugs
from src.config import settings

logger = logging.getLogger(__name__)


class ToolSelector:
    """
    Four-phase tool selection pipeline:
      1. Intent generation (LLM) — short keyword queries
      2. Semantic retrieval (Qdrant) — candidate tools per intent
      3. Per-tool evaluation (LLM, batched ≤5) — relevant/not + reasoning
      4. Argument binding (LLM) — configure args for approved tools only
    """

    def __init__(self, customer_id: str, run_id: str = None):
        self.customer_id = customer_id
        self.run_id = run_id
        self.llm = LLMFactory.get_model_for_agent("evidence_collector")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def select_tools(
        self,
        context: ToolSelectionContext,
        max_intents: int = 3,
    ) -> List[ToolSelection]:
        """Full pipeline: intents → retrieval → evaluation → arg binding."""
        # Phase 1
        intents = await self.generate_intents(context, max_intents)
        if not intents:
            logger.warning("ToolSelector: No intents generated.")
            return []
        logger.info(f"ToolSelector: Intents generated: {[{'query': i.query, 'category': i.category or 'NONE'} for i in intents]}")

        # Phase 2
        candidates = await self.retrieve_candidates(intents, context)
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

        logger.info(
            f"ToolSelector: {len(evaluations)} evaluated, "
            f"{len(approved)} approved"
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
                SystemMessage(content="You are a tool-search specialist. For each search query, assign an IT domain category. Always return JSON with objects containing 'query' and 'category' keys, never plain strings."),
                HumanMessage(content=prompt),
            ])
            parsed = json.loads(
                response.content.strip().replace("```json", "").replace("```", "")
            )
            raw_intents = parsed.get("intents", [])
            if isinstance(raw_intents, str):
                raw_intents = [raw_intents]
            raw_intents = raw_intents[:max_intents]

            valid_slugs = get_all_category_slugs()
            result = []
            for item in raw_intents:
                if isinstance(item, dict):
                    query = item.get("query", "")
                    cat = item.get("category", "")
                    if cat and cat not in valid_slugs:
                        cat = ""
                    result.append(ToolIntent(query=query, category=cat))
                elif isinstance(item, str) and item:
                    logger.warning(f"ToolSelector: LLM returned string intent (no category): '{item}'")
                    result.append(ToolIntent(query=item))
            return result

        except Exception as e:
            logger.warning(f"ToolSelector: Intent generation failed: {e}")
            return self._fallback_intents(context)

    # ------------------------------------------------------------------
    # Phase 2: Semantic Retrieval
    # ------------------------------------------------------------------

    async def retrieve_candidates(
        self, intents: List[ToolIntent], context: ToolSelectionContext,
    ) -> List[ToolCandidate]:
        """3-tier cascading search per intent, merge + deduplicate.

        Tier 1: exact category + vendor filter
        Tier 2: related categories + vendor filter (if Tier 1 insufficient)
        Tier 3: unfiltered semantic search (if Tier 2 still insufficient)
        Vendor fallback: repeat cascade without vendor if 0 results overall.
        """
        from src.core.qdrant import vector_store

        # Extract vendor filter from context
        vendor_filter = None
        if context.component and context.component.vendor:
            vendor_filter = context.component.vendor.lower()
        elif context.source_component and context.source_component.vendor:
            vendor_filter = context.source_component.vendor.lower()

        tier1_min = settings.TOOL_CATEGORY_TIER1_MIN
        tier2_min = settings.TOOL_CATEGORY_TIER2_MIN

        seen: Dict[str, ToolCandidate] = {}

        for intent in intents:
            category = intent.category
            intent_seen_before = len(seen)

            # --- Tier 1: exact category ---
            try:
                cat_filter = [category] if category else None
                payloads = await vector_store.search_tool_catalog(
                    intent=intent.query,
                    customer_id=self.customer_id,

                    vendor=vendor_filter,
                    read_only=True,
                    categories=cat_filter,
                )
                self._collect_payloads(payloads, intent.query, seen)
                tier1_new = len(seen) - intent_seen_before
                if tier1_new > 0:
                    logger.info(f"ToolSelector: Tier 1 produced {tier1_new} candidates for '{category or 'none'}'")
            except Exception as e:
                logger.warning(f"ToolSelector: Tier 1 search failed for '{intent.query[:50]}': {e}")

            # --- Tier 2: related categories ---
            intent_count = len(seen) - intent_seen_before
            if intent_count < tier1_min and category:
                try:
                    related = get_related_categories(category)
                    expanded = [category] + related
                    payloads = await vector_store.search_tool_catalog(
                        intent=intent.query,
                        customer_id=self.customer_id,
    
                        vendor=vendor_filter,
                        read_only=True,
                        categories=expanded,
                    )
                    before_t2 = len(seen)
                    self._collect_payloads(payloads, intent.query, seen)
                    tier2_new = len(seen) - before_t2
                    if tier2_new > 0:
                        logger.info(f"ToolSelector: Tier 2 produced {tier2_new} additional candidates for '{category}' + related")
                except Exception as e:
                    logger.warning(f"ToolSelector: Tier 2 search failed for '{intent.query[:50]}': {e}")

            # --- Tier 3: unfiltered ---
            intent_count = len(seen) - intent_seen_before
            if intent_count < tier2_min:
                try:
                    payloads = await vector_store.search_tool_catalog(
                        intent=intent.query,
                        customer_id=self.customer_id,
    
                        vendor=vendor_filter,
                        read_only=True,
                    )
                    before_t3 = len(seen)
                    self._collect_payloads(payloads, intent.query, seen)
                    tier3_new = len(seen) - before_t3
                    if tier3_new > 0:
                        logger.info(f"ToolSelector: Tier 3 (unfiltered) produced {tier3_new} additional candidates")
                except Exception as e:
                    logger.warning(f"ToolSelector: Tier 3 search failed for '{intent.query[:50]}': {e}")

        # Vendor fallback: retry cascade without vendor filter if no results
        if not seen and vendor_filter:
            logger.info(f"ToolSelector: No vendor-specific results for '{vendor_filter}'. Retrying without vendor filter.")
            for intent in intents:
                category = intent.category
                cat_filter = [category] if category else None
                try:
                    payloads = await vector_store.search_tool_catalog(
                        intent=intent.query,
                        customer_id=self.customer_id,
    
                        read_only=True,
                        categories=cat_filter,
                    )
                    self._collect_payloads(payloads, intent.query, seen)
                except Exception as e:
                    logger.warning(f"ToolSelector: Vendor fallback search failed for '{intent.query[:50]}': {e}")

            # If still empty after category-filtered no-vendor, try fully unfiltered
            if not seen:
                for intent in intents:
                    try:
                        payloads = await vector_store.search_tool_catalog(
                            intent=intent.query,
                            customer_id=self.customer_id,
        
                            read_only=True,
                        )
                        self._collect_payloads(payloads, intent.query, seen)
                    except Exception as e:
                        logger.warning(f"ToolSelector: Full fallback search failed for '{intent.query[:50]}': {e}")

        candidates = list(seen.values())
        logger.info(f"ToolSelector: {len(candidates)} unique candidates from {len(intents)} intents.")
        return candidates

    @staticmethod
    def _collect_payloads(
        payloads: List[Dict[str, Any]], intent_query: str,
        seen: Dict[str, "ToolCandidate"],
    ) -> None:
        """Add payloads to seen dict, deduplicating by tool_name."""
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
                source_intent=intent_query,
                catalog_context=payload.get("page_content", ""),
                vendor=payload.get("vendor", ""),
                method=payload.get("method", ""),
                read_only=payload.get("read_only", "true") == "true",
                categories=payload.get("categories", []),
                param_count=payload.get("param_count", 0),
                tier=payload.get("tier", 0),
                provides_identifiers=payload.get("provides_identifiers", []),
                requires_identifiers=payload.get("requires_identifiers", []),
                scope_params=payload.get("scope_params", []),
            )

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
                f"method: {c.method}, categories: {','.join(c.categories) or 'general'}): {c.description}{context_line}\n"
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
2. Is the tool's SCOPE appropriate (correct vendor, device type, domain)?
3. Will the tool's OUTPUT contribute useful diagnostic data?
4. CONFIGURATION-FIRST: Prefer config-reading tools over live traffic tools.

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

        # Build ticket context for arg binding (Phase 4 fix: LLM needs ticket text)
        ticket_section = ""
        if context.ticket_text:
            ticket_section = f'TICKET:\n"{context.ticket_text}"'

        # Build evidence context (useful on subsequent passes / multi-component loops)
        evidence_section = ""
        if context.evidence_summaries:
            evidence_section = f"PRIOR EVIDENCE:\n{context.evidence_summaries[:2000]}"

        # Build facts section from context (Change 1: include fact VALUES)
        facts_section = ""
        if context.facts:
            real_facts = {k: v for k, v in context.facts.items() if not k.startswith("_")}
            if real_facts:
                fact_lines = []
                for k, v in list(real_facts.items())[:30]:
                    val_str = str(v)[:200]
                    fact_lines.append(f"- {k}: {val_str}")
                facts_section = "KNOWN FACTS (from prior investigation):\n" + "\n".join(fact_lines)

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

{ticket_section}

{evidence_section}

{facts_section}

APPROVED TOOLS (configure arguments for each):
{tools_block}

{insights_text}

GUIDELINES:
1. For 'device', 'host', 'hostname' args: use the component ID of the executor-role component.
2. For target/address/destination parameters: extract values from the TICKET text and component metadata. Match IPs, subnets, hostnames, policy names, etc. from the ticket to the parameter's schema type and description. If the schema expects a single host and the available value is an aggregate (e.g. subnet, group, cluster), derive an appropriate singular value.
3. Use ALL metadata fields to fill matching parameters.
4. Analyze Schema: distinguish mandatory vs optional parameters.
5. OPERATIONAL vs CONTEXTUAL parameters — classify each required parameter by its schema description:
   - OPERATIONAL: controls API behavior (result limits, pagination, timeouts, sort order, output format, batch size). Descriptions typically say "max", "limit", "number of", "timeout", "page", "sort", "count". For these, assign a sensible default (e.g., 100 for result counts, 30 for timeouts). This is standard API usage, not guessing.
   - CONTEXTUAL: identifies WHAT to query (IPs, hostnames, policy names, interfaces, resource IDs). These MUST come from TICKET, KNOWN FACTS, PRIOR EVIDENCE, or metadata.
   When uncertain, treat as contextual.
6. ANTI-HALLUCINATION: Do NOT invent CONTEXTUAL parameter values. Bind contextual params only from TICKET, KNOWN FACTS, PRIOR EVIDENCE, or component metadata. For OPERATIONAL parameters, provide sensible defaults per guideline 5.
7. READ-ONLY only. No modify/delete/configure actions.
8. Use KNOWN FACTS values to bind parameters when a fact key/value matches a parameter's purpose.

Return ONLY a JSON list (one entry per approved tool):
[
    {{"name": "tool_name_1", "args": {{...}}}},
    {{"name": "tool_name_2", "args": {{...}}}}
]
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

                # Deterministic: check schema required fields vs bound args
                cand = candidate_map.get(name)
                missing = {}
                if cand and cand.args_schema:
                    required_fields = cand.args_schema.get("required", [])
                    properties = cand.args_schema.get("properties", {})
                    for field in required_fields:
                        if field not in args or args[field] is None:
                            prop = properties.get(field, {})
                            missing[field] = prop.get("description", f"required parameter '{field}'")

                selections.append(ToolSelection(
                    name=name, args=args, evaluation=ev,
                    missing_params=missing,
                    requires_identifiers=cand.requires_identifiers if cand else [],
                    tier=cand.tier if cand else 0,
                ))

            # Recover approved tools the LLM omitted — tier-aware recovery
            bound_names = {s.name for s in selections}
            omitted_count = 0
            for ev in approved:
                if ev.tool_name not in bound_names:
                    cand = candidate_map.get(ev.tool_name)
                    if not cand:
                        continue
                    schema = cand.args_schema or {}
                    required_fields = schema.get("required", [])
                    properties = schema.get("properties", {})

                    # Case A: No required params — recover with empty args
                    if not required_fields:
                        selections.append(ToolSelection(
                            name=ev.tool_name, args={}, evaluation=ev,
                            missing_params={},
                            requires_identifiers=cand.requires_identifiers,
                            tier=cand.tier,
                        ))
                        logger.info(f"ToolSelector: Recovered {ev.tool_name} (no required params)")
                        continue

                    scope_fields = set(cand.scope_params) & set(required_fields)
                    identifier_fields = set(cand.requires_identifiers) & set(required_fields)
                    unclassified_fields = set(required_fields) - scope_fields - identifier_fields

                    # Case B: Tier 2 tool or has requires_identifiers — forward to prereq resolution
                    if cand.tier == 2 or cand.requires_identifiers:
                        partial_args = self._bind_scope_params_from_context(
                            scope_fields, properties, context,
                        )
                        missing = {}
                        for field in (identifier_fields | unclassified_fields):
                            if field not in partial_args:
                                prop = properties.get(field, {})
                                missing[field] = prop.get("description", f"required parameter '{field}'")
                        selections.append(ToolSelection(
                            name=ev.tool_name, args=partial_args, evaluation=ev,
                            missing_params=missing,
                            requires_identifiers=cand.requires_identifiers,
                            tier=cand.tier,
                        ))
                        logger.info(
                            f"ToolSelector: Tier 2 tool {ev.tool_name} promoted to prereq resolution "
                            f"(missing: {list(missing.keys())})"
                        )
                        continue

                    # Case C: Tier 1 tool — try deterministic scope binding
                    if cand.tier == 1:
                        partial_args = self._bind_scope_params_from_context(
                            set(required_fields), properties, context,
                        )
                        missing = {}
                        for field in required_fields:
                            if field not in partial_args:
                                prop = properties.get(field, {})
                                missing[field] = prop.get("description", f"required parameter '{field}'")
                        selections.append(ToolSelection(
                            name=ev.tool_name, args=partial_args, evaluation=ev,
                            missing_params=missing,
                            requires_identifiers=cand.requires_identifiers,
                            tier=cand.tier,
                        ))
                        if missing:
                            logger.info(
                                f"ToolSelector: Tier 1 tool {ev.tool_name} partially bound "
                                f"(missing: {list(missing.keys())})"
                            )
                        else:
                            logger.info(f"ToolSelector: Recovered Tier 1 tool {ev.tool_name} via scope binding")
                        continue

                    # Case D: Unclassified (tier==0, no metadata) — trust LLM omission
                    omitted_count += 1
                    logger.info(
                        f"ToolSelector: LLM omitted unclassified tool {ev.tool_name} "
                        f"(required: {required_fields}) — not recovering"
                    )

            # Metrics logging (Change 5)
            bound_count = len([s for s in selections if not s.missing_params])
            partial_count = len([s for s in selections if s.missing_params])
            logger.info(
                f"ToolSelector: Binding result — {bound_count} fully bound, "
                f"{partial_count} with missing params, {omitted_count} deliberately omitted"
            )
            return selections

        except Exception as e:
            logger.error(f"ToolSelector: Arg binding failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Phase 5: Prerequisite Resolution
    # ------------------------------------------------------------------

    async def resolve_prerequisites(
        self,
        selections: List[ToolSelection],
        components: list,
        state: dict,
        store,
        executed_signatures: set,
        max_prereqs: int = 4,
    ) -> tuple:
        """
        2-tier execution orchestrator:
        1. Execute Tier 1 tools (discovery/list) → collect output as context
        2. Rebind Tier 2 tools using Tier 1 output
        3. Fallback: search for additional Tier 1 tools if needed

        Returns (updated_selections, prereq_evidence_snapshots).
        Tier 1 tools are removed from selections (already executed, evidence captured).
        """
        from src.core.adaptive_executor import AdaptiveExecutor
        from src.core.registry import CapabilityRegistry as _CR
        from src.core.safety import is_safe_tool, is_tool_allowed_for_tenant
        import hashlib as _hl

        # --- Step 1: Separate selections by readiness ---
        tier1_ready = []      # Tier 1, fully bound → execute now for context
        needs_data = []       # Has missing_params → needs Tier 1 output
        pass_through = []     # Fully bound, not Tier 1 → caller executes

        for sel in selections:
            if not sel.missing_params and sel.tier == 1:
                tier1_ready.append(sel)
            elif sel.missing_params:
                needs_data.append(sel)
            else:
                pass_through.append(sel)

        if not needs_data:
            # No tools waiting for data → Tier 1 tools pass to caller for normal execution
            return selections, []

        logger.info(
            f"ToolSelector: 2-tier orchestration — {len(tier1_ready)} Tier 1 ready, "
            f"{len(needs_data)} need data, {len(pass_through)} pass-through"
        )

        # --- Step 2: Execute Tier 1 tools → collect context ---
        tier1_evidence = []
        tier1_outputs: List[tuple] = []  # (tool_name, output_text)

        for sel in tier1_ready:
            sig_norm = json.dumps(sel.args or {}, sort_keys=True, default=str)
            sig = f"{sel.name}::{_hl.sha256(sig_norm.encode()).hexdigest()[:16]}"
            if sig in executed_signatures:
                logger.info(f"ToolSelector: Tier 1 {sel.name} already executed, skipping")
                continue

            tool = _CR.get_tool(sel.name)
            if not tool:
                continue
            if not is_safe_tool(sel.name, sel.args):
                continue
            if not await is_tool_allowed_for_tenant(sel.name, self.customer_id):
                continue

            try:
                executor = AdaptiveExecutor(customer_id=self.customer_id, run_id=self.run_id)
                comp = self._find_component_for_sel(sel, components)
                comp_meta = json.dumps(comp.metadata, default=str) if comp and comp.metadata else "{}"
                exec_context = (
                    f"Ticket: {state.get('ticket', {})}\n"
                    f"Component: {comp.id if comp else 'unknown'} (metadata={comp_meta})\n"
                    f"Goal: Tier 1 discovery — gather identifiers for Tier 2 tools"
                )
                output = await executor.execute(
                    tool, sel.args, exec_context, intent=sel.evaluation.reasoning,
                )
                snapshot = await store.save_evidence(
                    tool_name=sel.name, tool_args=sel.args, content=output,
                    summary=f"Tier 1 discovery: {sel.evaluation.reasoning}",
                )
                tier1_evidence.append(snapshot)
                executed_signatures.add(sig)
                tier1_outputs.append((sel.name, output))
                logger.info(
                    f"ToolSelector: Tier 1 executed {sel.name} → "
                    f"context for {len(needs_data)} tools needing data"
                )
            except Exception as e:
                logger.warning(f"ToolSelector: Tier 1 execution failed for {sel.name}: {e}")

        # --- Step 3: Rebind needs_data tools with aggregated Tier 1 context ---
        if tier1_outputs:
            tier1_context = "\n\n".join(
                f"=== {name} output ===\n{out[:3000]}" for name, out in tier1_outputs
            )
            for i, sel in enumerate(needs_data):
                comp = self._find_component_for_sel(sel, components)
                needs_data[i] = await self._rebind_with_prereq_data(
                    sel, tier1_context, comp or (components[0] if components else None),
                )

        # --- Step 4: Fallback — search for additional Tier 1 tools for STILL-missing ---
        still_missing = [s for s in needs_data if s.missing_params and len(s.missing_params) <= 3]
        if still_missing:
            resolved_count = 0
            # Group by (requires_identifiers or missing_params, component_id)
            groups: Dict[tuple, list] = {}
            for sel in still_missing:
                comp = self._find_component_for_sel(sel, components)
                comp_id = comp.id if comp else "unknown"
                if sel.requires_identifiers:
                    group_key = frozenset(sel.requires_identifiers)
                else:
                    group_key = frozenset(sel.missing_params.keys())
                groups.setdefault((group_key, comp_id), []).append((sel, comp))

            for (id_keys, comp_id), group_entries in groups.items():
                if resolved_count >= max_prereqs:
                    break

                representative_sel, target_comp = group_entries[0]
                search_identifiers = list(id_keys)
                missing_desc = "; ".join(
                    f"{k}: {v}" for k, v in representative_sel.missing_params.items()
                )
                tool_names_in_group = [s.name for s, _ in group_entries]
                logger.info(
                    f"ToolSelector: Fallback prereq search — identifiers: {search_identifiers}, "
                    f"tools: {tool_names_in_group}"
                )

                # Strategy A: Identifier-based Qdrant search for Tier 1 tools
                prereq_selections = []
                try:
                    from src.core.qdrant import vector_store
                    vendor_filter = target_comp.vendor.lower() if target_comp and target_comp.vendor else None

                    payloads = await vector_store.search_tool_catalog(
                        intent=f"list discover {' '.join(search_identifiers)}",
                        customer_id=self.customer_id,
                        limit=5,
                        vendor=vendor_filter,
                        read_only=True,
                        tier=1,
                        provides_identifiers=search_identifiers,
                    )
                    if payloads:
                        logger.info(
                            f"ToolSelector: Found {len(payloads)} Tier 1 candidates "
                            f"for {search_identifiers}"
                        )
                        tier1_candidates = []
                        for p in payloads:
                            t_name = p.get("tool_name")
                            tool = _CR.get_tool(t_name)
                            if not tool or not _CR._is_safe(t_name):
                                continue
                            tier1_candidates.append(ToolCandidate(
                                tool_name=t_name,
                                description=tool.description or t_name,
                                args_schema=tool.args_schema.model_json_schema() if tool.args_schema else {},
                                vendor=p.get("vendor", ""),
                                tier=p.get("tier", 1),
                                provides_identifiers=p.get("provides_identifiers", []),
                                scope_params=p.get("scope_params", []),
                            ))
                        if tier1_candidates:
                            tier1_ctx = ToolSelectionContext(
                                ticket_text=f"Need to discover: {missing_desc}",
                                component=target_comp,
                                components=components,
                                facts=state.get("facts", {}),
                                mode="evidence",
                            )
                            evals = await self.evaluate_candidates(tier1_candidates, tier1_ctx)
                            approved_evals = [e for e in evals if e.relevant]
                            if approved_evals:
                                approved_evals.sort(key=lambda e: e.priority)
                                prereq_selections = await self.bind_arguments(
                                    approved_evals, tier1_candidates, tier1_ctx,
                                )
                                prereq_selections = [p for p in prereq_selections if not p.missing_params]
                except Exception as e:
                    logger.warning(f"ToolSelector: Fallback identifier search failed: {e}")

                # Strategy B: Generic select_tools() fallback
                if not prereq_selections:
                    prereq_ctx = ToolSelectionContext(
                        ticket_text=f"Need to discover: {missing_desc}",
                        component=target_comp,
                        components=components,
                        facts=state.get("facts", {}),
                        mode="evidence",
                    )
                    try:
                        prereq_selections = await self.select_tools(prereq_ctx, max_intents=1)
                    except Exception as e:
                        logger.warning(f"ToolSelector: Prereq search failed for {tool_names_in_group}: {e}")
                        continue
                    prereq_selections = [p for p in prereq_selections if not p.missing_params]

                if not prereq_selections:
                    logger.info(f"ToolSelector: No fully-bindable prereq found for {tool_names_in_group}")
                    continue

                # Execute best prereq tool
                prereq_sel = prereq_selections[0]
                sig_norm = json.dumps(prereq_sel.args or {}, sort_keys=True, default=str)
                prereq_sig = f"{prereq_sel.name}::{_hl.sha256(sig_norm.encode()).hexdigest()[:16]}"
                if prereq_sig in executed_signatures:
                    logger.info(f"ToolSelector: Prereq {prereq_sel.name} already executed, skipping")
                    continue

                prereq_tool = _CR.get_tool(prereq_sel.name)
                if not prereq_tool:
                    continue
                if not is_safe_tool(prereq_sel.name, prereq_sel.args):
                    continue
                if not await is_tool_allowed_for_tenant(prereq_sel.name, self.customer_id):
                    continue

                try:
                    executor = AdaptiveExecutor(customer_id=self.customer_id, run_id=self.run_id)
                    comp_meta = json.dumps(target_comp.metadata, default=str) if target_comp and target_comp.metadata else "{}"
                    exec_context = (
                        f"Ticket: {state.get('ticket', {})}\n"
                        f"Component: {target_comp.id if target_comp else 'unknown'} (metadata={comp_meta})\n"
                        f"Goal: Fetch prerequisite data for {tool_names_in_group}: {missing_desc}"
                    )
                    output = await executor.execute(
                        prereq_tool, prereq_sel.args, exec_context,
                        intent=f"Prerequisite for {tool_names_in_group}",
                    )
                    snapshot = await store.save_evidence(
                        tool_name=prereq_sel.name, tool_args=prereq_sel.args,
                        content=output,
                        summary=f"Prerequisite for {tool_names_in_group}: {missing_desc}",
                    )
                    tier1_evidence.append(snapshot)
                    executed_signatures.add(prereq_sig)
                    logger.info(
                        f"ToolSelector: Fallback discovery {prereq_sel.name} executed → "
                        f"enables: {tool_names_in_group}"
                    )

                    # Rebind all tools in group with prereq output
                    for sel, sel_comp in group_entries:
                        updated = await self._rebind_with_prereq_data(
                            sel, output, sel_comp or target_comp,
                        )
                        for idx, s in enumerate(needs_data):
                            if s.name == sel.name and s is sel:
                                needs_data[idx] = updated
                                break
                    resolved_count += 1

                except Exception as e:
                    logger.warning(f"ToolSelector: Fallback prereq execution failed for {prereq_sel.name}: {e}")

        # --- Step 5: Return ---
        # Tier 1 tools removed from selections (already executed, evidence captured)
        final_selections = pass_through + needs_data
        bound_count = len([s for s in final_selections if not s.missing_params])
        still_count = len([s for s in final_selections if s.missing_params])
        logger.info(
            f"ToolSelector: 2-tier resolution complete — "
            f"{len(tier1_evidence)} Tier 1 executed, "
            f"{bound_count} fully bound, {still_count} still missing params"
        )
        return final_selections, tier1_evidence

    def _find_component_for_sel(self, sel: ToolSelection, components: list):
        """Find the component associated with a tool selection."""
        for c in components:
            if c.id in str(sel.args.values()):
                return c
        return components[0] if components else None

    async def resolve_runtime_dependency(
        self,
        failed_tool_name: str,
        failed_tool_args: dict,
        error: "MissingDependencyError",
        component,
        components: list,
        state: dict,
        store,
        executed_signatures: set,
    ) -> tuple:
        """
        Post-execution recovery: when a tool fails at runtime due to missing data
        only discoverable at execution time.

        Returns (resolved_args | None, evidence_snapshots).
        Single-depth: resolution tool itself cannot trigger recursive recovery.
        """
        from src.core.adaptive_executor import AdaptiveExecutor, MissingDependencyError
        from src.core.safety import is_safe_tool, is_tool_allowed_for_tenant
        from src.core.registry import CapabilityRegistry

        deps = "; ".join(error.dependencies)
        source_hint = error.suggested_source or ""
        evidence_snapshots = []

        # 1. Find resolution tools via full ToolSelector pipeline
        prereq_ctx = ToolSelectionContext(
            ticket_text=f"Need to discover: {deps}. Hint: {source_hint}",
            component=component,
            components=components,
            facts=state.get("facts", {}),
            mode="evidence",
        )

        try:
            prereq_selections = await self.select_tools(
                prereq_ctx, max_intents=1
            )
        except Exception as e:
            logger.warning(f"ToolSelector: Runtime dep search failed for {failed_tool_name}: {e}")
            return None, []

        # 2. Filter to fully-bindable only (single-depth — no recursive prereqs)
        prereq_selections = [p for p in prereq_selections if not p.missing_params]
        if not prereq_selections:
            logger.info(f"ToolSelector: No fully-bindable resolution tool found for {failed_tool_name}")
            return None, []

        prereq_sel = prereq_selections[0]
        prereq_tool_name = prereq_sel.name
        prereq_tool_args = prereq_sel.args

        # 3. Dedup check
        import hashlib as _hl
        sig_norm = json.dumps(prereq_tool_args or {}, sort_keys=True, default=str)
        prereq_sig = f"{prereq_tool_name}::{_hl.sha256(sig_norm.encode()).hexdigest()[:16]}"
        if prereq_sig in executed_signatures:
            logger.info(f"ToolSelector: Resolution tool {prereq_tool_name} already executed, skipping")
            return None, []

        # 4. Safety + governance checks
        prereq_tool = CapabilityRegistry.get_tool(prereq_tool_name)
        if not prereq_tool:
            return None, []
        if not is_safe_tool(prereq_tool_name, prereq_tool_args):
            logger.warning(f"ToolSelector: Resolution tool {prereq_tool_name} failed safety check")
            return None, []
        if not await is_tool_allowed_for_tenant(prereq_tool_name, self.customer_id):
            logger.warning(f"ToolSelector: Resolution tool {prereq_tool_name} not allowed for tenant")
            return None, []

        # 5. Execute resolution tool (catch MissingDependencyError to prevent recursion)
        try:
            executor = AdaptiveExecutor(customer_id=self.customer_id, run_id=self.run_id)
            comp_meta = json.dumps(component.metadata, default=str) if component and component.metadata else "{}"
            exec_context = (
                f"Ticket: {state.get('ticket', {})}\n"
                f"Component: {component.id if component else 'unknown'} (metadata={comp_meta})\n"
                f"Goal: Fetch runtime dependency for {failed_tool_name}: {deps}"
            )
            output = await executor.execute(
                prereq_tool, prereq_tool_args, exec_context,
                intent=f"Runtime resolution for {failed_tool_name}"
            )

            snapshot = await store.save_evidence(
                tool_name=prereq_tool_name,
                tool_args=prereq_tool_args,
                content=output,
                summary=f"Runtime resolution for {failed_tool_name}: {deps}"
            )
            evidence_snapshots.append(snapshot)
            executed_signatures.add(prereq_sig)
            logger.info(f"ToolSelector: Resolution tool {prereq_tool_name} executed successfully")

        except MissingDependencyError:
            logger.warning(f"ToolSelector: Resolution tool {prereq_tool_name} also has missing deps — aborting (no recursion)")
            return None, evidence_snapshots
        except Exception as e:
            logger.warning(f"ToolSelector: Resolution tool {prereq_tool_name} execution failed: {e}")
            return None, evidence_snapshots

        # 6. Build a temporary ToolSelection for the failed tool to rebind missing params
        failed_tool = CapabilityRegistry.get_tool(failed_tool_name)
        if not failed_tool:
            return None, evidence_snapshots

        schema = failed_tool.args_schema.model_json_schema() if failed_tool.args_schema else {}
        required_fields = schema.get("required", [])
        properties = schema.get("properties", {})
        missing_params = {}
        for field in required_fields:
            if field not in failed_tool_args or failed_tool_args[field] is None:
                prop = properties.get(field, {})
                missing_params[field] = prop.get("description", f"required parameter '{field}'")
        # Also include the deps from the error as missing
        for dep in error.dependencies:
            dep_key = dep.strip().split(":")[0].strip().lower().replace(" ", "_")
            if dep_key not in missing_params:
                missing_params[dep_key] = dep

        temp_selection = ToolSelection(
            name=failed_tool_name,
            args=dict(failed_tool_args),
            evaluation=ToolEvaluation(
                tool_name=failed_tool_name, relevant=True,
                reasoning="Runtime dependency resolution", priority=1,
            ),
            missing_params=missing_params,
        )

        # 7. Extract values from resolution output
        updated_sel = await self._rebind_with_prereq_data(
            temp_selection, output, component
        )

        if updated_sel.args != failed_tool_args:
            logger.info(f"ToolSelector: Resolved runtime params for {failed_tool_name}: {set(updated_sel.args.keys()) - set(failed_tool_args.keys()) or 'updated values'}")
            return updated_sel.args, evidence_snapshots

        logger.info(f"ToolSelector: Could not extract runtime params for {failed_tool_name}")
        return None, evidence_snapshots

    async def _rebind_with_prereq_data(
        self, sel: ToolSelection, prereq_output: str, comp
    ) -> ToolSelection:
        """
        Use LLM to extract missing parameter values from prerequisite tool output.
        Anti-hallucination: LLM told to only use data present in the output.
        """
        if not sel.missing_params:
            return sel

        missing_desc = json.dumps(sel.missing_params, indent=2)
        existing_args = json.dumps(sel.args, indent=2)
        comp_info = f"Component: {comp.id} (role={comp.role})" if comp else "No component"

        prompt = f"""You have prerequisite tool output that may contain values for missing parameters.

TARGET TOOL: {sel.name}
EXISTING ARGS: {existing_args}
MISSING PARAMETERS (need values):
{missing_desc}

{comp_info}

PREREQUISITE OUTPUT:
{prereq_output[:3000]}

RULES:
1. ONLY extract values that are EXPLICITLY present in the prerequisite output above.
2. Do NOT invent, guess, or assume any values.
3. Match parameter descriptions to data in the output.
4. Return a JSON object with ONLY the parameters you can fill from the output.

Return ONLY a JSON object:
{{"extracted": {{"param_name": "value_from_output", ...}}}}

If no values can be extracted, return: {{"extracted": {{}}}}
"""

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="You extract parameter values from tool output. Never invent data."),
                HumanMessage(content=prompt),
            ])
            raw = json.loads(
                response.content.strip().replace("```json", "").replace("```", "")
            )
            extracted = raw.get("extracted", {})

            if extracted:
                new_args = dict(sel.args)
                new_missing = dict(sel.missing_params)
                for k, v in extracted.items():
                    if k in new_missing and v is not None:
                        new_args[k] = v
                        del new_missing[k]
                        logger.info(f"ToolSelector: Resolved param '{k}' for {sel.name}")

                return ToolSelection(
                    name=sel.name,
                    args=new_args,
                    evaluation=sel.evaluation,
                    missing_params=new_missing,
                    requires_identifiers=sel.requires_identifiers,
                    tier=sel.tier,
                )
            return sel

        except Exception as e:
            logger.warning(f"ToolSelector: Rebind failed for {sel.name}: {e}")
            return sel

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

    @staticmethod
    def _bind_scope_params_from_context(
        scope_fields: set,
        properties: dict,
        context: "ToolSelectionContext",
    ) -> Dict[str, Any]:
        """
        Deterministic scope-param binding from Component metadata.
        Maps common scope param names (host, device, ip, hostname, etc.)
        to values from the component's id, ref, or metadata dict.
        No LLM call — pure metadata lookup.
        """
        comp = context.component or context.source_component
        if not comp:
            return {}

        pool: Dict[str, str] = {}
        pool["device"] = comp.id
        pool["host"] = comp.id
        pool["hostname"] = comp.id
        ip_val = comp.metadata.get("ip", comp.metadata.get("management_ip", ""))
        if ip_val:
            pool["ip"] = ip_val
            pool["device_ip"] = ip_val
        for k, v in comp.metadata.items():
            if isinstance(v, str) and v:
                pool[k.lower()] = v
        if comp.ref:
            pool.setdefault("name", comp.ref)

        bound: Dict[str, Any] = {}
        for field in scope_fields:
            fl = field.lower()
            if fl in pool and pool[fl]:
                bound[field] = pool[fl]
            else:
                for pk, pv in pool.items():
                    if pk in fl and pv:
                        bound[field] = pv
                        break
        return bound

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
                    categories=meta["categories"],
                    param_count=meta["param_count"],
                ))

        return candidates

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

        taxonomy = get_categories_prompt_block()

        return f"""Ticket: "{context.ticket_text}"
Component: {comp_id} (Role: {comp_role}). {vendor_ctx}
All components: {all_components_str}

Task: Generate 1-{max_intents} SHORT tool-search queries to find the right diagnostic tools for this component.
For EACH query, assign exactly ONE IT domain category from the taxonomy below.

## IT Domain Categories
{taxonomy}

RULES:
1. Each query must be 2-6 words — like a search engine query, NOT a sentence.
2. Do NOT include vendor or product names (appliance names) — vendor filtering is applied automatically. Focus on WHAT the tool does.
3. Focus on the CATEGORY of tool needed or explicit feature names.
4. Do NOT include specific tenant data, or ticket-specific details (Hostnames, IPs, IDs, etc)— those are for tool arguments, not tool search.
5. Do NOT write sentences or descriptions — write search keywords only.
6. CONFIGURATION-FIRST: Prefer tools that read existing configuration (routes, policies, rules, definitions) over live traffic tools (debug flows, captures, sniffers, sessions).
7. The "category" must be a valid slug from the taxonomy above.
{path_section}
EXAMPLES (do not copy literally, adapt to the ticket):
{{"intents": [{{"query": "routing table", "category": "routing"}}, {{"query": "memory performance", "category": "performance"}}]}}
{{"intents": [{{"query": "database replication status", "category": "database"}}, {{"query": "connection pool metrics", "category": "performance"}}]}}

CRITICAL: Each intent MUST be a JSON object with "query" and "category" keys. Do NOT return plain strings.

Return ONLY a JSON object:
{{"intents": [{{"query": "query 1", "category": "slug"}}, {{"query": "query 2", "category": "slug"}}]}}
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

        taxonomy = get_categories_prompt_block()

        return f"""Hypothesis: "{hyp.summary if hyp else 'unknown'}"
Rationale: {hyp.rationale if hyp else 'N/A'}
Components: {components_str}
Facts collected: {facts_keys}
{evidence_section}
Task: Generate 1-{max_intents} SHORT tool-search queries (2-6 words each) to find tools
that verify or disprove this hypothesis.
For EACH query, assign exactly ONE IT domain category from the taxonomy below.

## IT Domain Categories
{taxonomy}

RULES:
1. Each query must be 2-6 words — keyword-style, NOT a sentence.
2. Do NOT include vendor or product names — vendor filtering is applied automatically.
3. Focus on the CATEGORY of tool needed or explicit feature names.
4. CONFIGURATION-FIRST: Prefer config-reading tools over live traffic tools.
5. Do NOT include IPs or ticket-specific details.
6. The "category" must be a valid slug from the taxonomy above.

CRITICAL: Each intent MUST be a JSON object with "query" and "category" keys. Do NOT return plain strings.

Return ONLY a JSON object:
{{"intents": [{{"query": "query 1", "category": "slug"}}, {{"query": "query 2", "category": "slug"}}]}}
"""

    def _build_relational_intent_prompt(self, context: ToolSelectionContext, max_intents: int) -> str:
        src = context.source_component
        dst = context.target_component
        all_str = ", ".join(f"{c.id} ({c.role})" for c in context.components) if context.components else "none"

        taxonomy = get_categories_prompt_block()

        return f"""Ticket: "{context.ticket_text}"
Source component: {src.id if src else 'unknown'} (Role: {src.role if src else 'unknown'}, Vendor: {src.vendor or 'unknown' if src else 'unknown'})
Destination component: {dst.id if dst else 'unknown'} (Role: {dst.role if dst else 'unknown'}, Vendor: {dst.vendor or 'unknown' if dst else 'unknown'})
All components: {all_str}

Task: Generate 1-{max_intents} SHORT tool-search queries to find tools that check the RELATIONSHIP
or REACHABILITY between source and destination.
For EACH query, assign exactly ONE IT domain category from the taxonomy below.

## IT Domain Categories
{taxonomy}

RULES:
1. Each query must be 2-6 words — keyword-style, NOT a sentence.
2. Do NOT include vendor or product names — vendor filtering is applied automatically.
3. Focus on relational diagnostics.
4. CONFIGURATION-FIRST: Prefer config-based tools (persistant or runtime) over live traffic tools.
5. The "category" must be a valid slug from the taxonomy above.

CRITICAL: Each intent MUST be a JSON object with "query" and "category" keys. Do NOT return plain strings.

Return ONLY a JSON object:
{{"intents": [{{"query": "query 1", "category": "slug"}}, {{"query": "query 2", "category": "slug"}}]}}
"""

    # ------------------------------------------------------------------
    # Fallback intents
    # ------------------------------------------------------------------

    # def _fallback_intents(self, context: ToolSelectionContext) -> List[ToolIntent]:
    #     """Produce basic intents when LLM generation fails."""
    #     if context.mode == "relational":
    #         return [
    #             ToolIntent(query="route lookup"),
    #             ToolIntent(query="policy check"),
    #         ]
    #     elif context.mode == "investigation" and context.hypothesis:
    #         return [
    #             ToolIntent(query="system status health"),
    #             ToolIntent(query="configuration check"),
    #         ]
    #     else:
    #         comp = context.component
    #         role = comp.role if comp else "system"
    #         return [
    #             ToolIntent(query=f"{role} status"),
    #             ToolIntent(query=f"{role} configuration"),
    #         ]
