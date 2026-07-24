# Skill: Logical Investigation Method

Resolve technical requests by building and verifying a complete causal explanation — never by mistaking partial signals for a diagnosis.

## Process

1. Define the failure: the exact operation that fails, between which endpoints, since when, for whom, and what the expected behavior is. Investigate the specific failing flow, never the general health of the reported component.
2. Discover the environment before reasoning about it — the ticket describes an experience, not the system.
3. Model the system: components, dependencies, states, and the conditions that must hold for the operation to succeed. When the request names an application or service, write down its dependency profile — endpoints, protocols, resolution steps, and the order they are exercised — before collecting evidence.
4. Keep an evidence ledger: classify each datum as observed fact, inference, assumption, or missing — with its source, time window, scope, and visibility limits.
5. Generate diverse hypotheses across cause categories: local fault, external dependency, configuration, state, capacity, security control, recent change. Do not adopt a lead hypothesis yet; do not restate one explanation in different words.
6. For each hypothesis, predict in advance: what evidence should exist if it is true, what would weaken it, and what test distinguishes it from the alternatives.
7. Choose discriminating tests first — the ones that reduce the most uncertainty. Before each tool call, state the expected result and what each possible outcome would imply.
8. Attribute evidence to the failing flow only through identifying keys (endpoint, name, signature, session, log field, correlated time). Compatibility is not attribution; coincidence of port, address, or timing is not attribution.
9. Update the model after every result: keep what is proven, re-rank or discard hypotheses, and pick the next test by information value. Never repeat a query without stating what new information it can yield.
10. Verify causally before concluding: a valid cause must explain the chain forward — cause → state change → propagation → observed symptom. Any undemonstrated link means the conclusion is still a hypothesis.
11. To conclude a component is not the cause, enumerate every mechanism by which it could affect the failing flow and verify each one; anything less supports only "not proven to affect it", stated with that exact scope.
12. Distinguish cause, trigger, symptom, and contributing factor. Do not confuse correlation with cause, configured state with effective state, or absence of evidence with evidence of absence. Do not invent meaning for ambiguous or failed outputs. Finding a normal condition is not a diagnosis.

## Pre-Closure Check

Before submitting findings, answer honestly:

- Am I confirming my first idea instead of testing alternatives?
- Did I mistake partial or generic success for the specific failing flow working?
- Did I treat missing data as absence of the problem?
- Did the tools I used actually have visibility over what I am concluding about?
- Does my conclusion explain all facts, including the contradictory ones?
- Does the strength of my claim exceed what the evidence supports?

Close only when one hypothesis explains the symptom and its propagation, the evidence supports it, and the main alternatives were ruled out. Otherwise state the boundary reached and the minimal missing evidence that would settle it.

If two consecutive iterations produce no new facts, or the evidence contradicts
every open hypothesis, call `load_domain_skill("lateral_thinking")` before
declaring the case blocked.

If a remote or centralized log backend errors or reports disabled, do not
conclude logs are unavailable — call `load_domain_skill("logs")` and check the
device's local log stores first.

Reasoning format:

**Symptom → Model → Hypotheses → Predictions → Discriminating test → Evidence → Update → Causal chain → Calibrated conclusion**
