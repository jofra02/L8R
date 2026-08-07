"""submit_findings item coercion + findings conversion safety net (no DB, no network).

Regression for the incident where the LLM submitted findings list items as
plain strings; the model conversion crashed with "'str' object has no
attribute 'get'" AFTER the investigation had completed, and the run was
persisted as failed with all findings lost.

Run: uv run pytest src/testing/test_engineer_findings.py
"""

from src.agents.engineer import _convert_findings
from src.agents.engineer_tools import create_engineer_tools


def _submit_tool():
    tools, state = create_engineer_tools(customer_id="acme", run_id="", ticket_id="t1")
    submit = next(t for t in tools if t.name == "submit_findings")
    return submit, state


async def _invoke(submit, **overrides):
    payload = {
        "summary": "## Report",
        "hypotheses": "[]",
        "facts": "[]",
        "plan": "{}",
        "case_status": "resolved",
    }
    payload.update(overrides)
    return await submit.ainvoke(payload)


# ---------------------------------------------------------------------------
# submit_findings coercion
# ---------------------------------------------------------------------------

async def test_clean_input_stored_without_warnings():
    submit, state = _submit_tool()
    message = await _invoke(
        submit,
        hypotheses='[{"summary": "real", "confidence": 0.9}]',
        facts='[{"key": "k", "value": "v"}]',
        plan='{"diagnosis_steps": [{"description": "d"}]}',
    )
    assert message == "Findings submitted successfully."
    assert state.findings["hypotheses"] == [{"summary": "real", "confidence": 0.9}]
    assert state.findings["facts"] == [{"key": "k", "value": "v"}]
    assert state.findings["plan"] == {"diagnosis_steps": [{"description": "d"}]}


async def test_string_hypothesis_is_coerced_with_warning():
    submit, state = _submit_tool()
    message = await _invoke(
        submit, hypotheses='["just a string", {"summary": "real", "confidence": 0.9}]'
    )
    assert state.findings["hypotheses"][0] == {"summary": "just a string"}
    assert state.findings["hypotheses"][1] == {"summary": "real", "confidence": 0.9}
    assert "warnings" in message and "hypotheses[0]" in message


async def test_string_fact_is_coerced_to_key_value():
    submit, state = _submit_tool()
    message = await _invoke(submit, facts='["disk full"]')
    assert state.findings["facts"] == [{"key": "fact_0", "value": "disk full"}]
    assert "facts[0]" in message


async def test_plan_string_steps_and_string_value_are_coerced():
    submit, state = _submit_tool()
    message = await _invoke(
        submit,
        plan='{"diagnosis_steps": ["check logs", {"description": "d"}], "validation": "run test"}',
    )
    plan = state.findings["plan"]
    assert plan["diagnosis_steps"] == [{"description": "check logs"}, {"description": "d"}]
    assert plan["validation"] == [{"description": "run test"}]
    assert "plan.diagnosis_steps[0]" in message and "plan.validation" in message


async def test_non_object_non_string_item_is_dropped():
    submit, state = _submit_tool()
    message = await _invoke(submit, hypotheses="[42]")
    assert state.findings["hypotheses"] == []
    assert "dropped" in message


# ---------------------------------------------------------------------------
# Conversion safety net (engineer._convert_findings)
# ---------------------------------------------------------------------------

def _findings(**overrides):
    base = {
        "summary": "## Report",
        "hypotheses": [],
        "facts": [],
        "plan": {},
        "case_status": "resolved",
        "evidence_refs": [],
    }
    base.update(overrides)
    return base


def test_unconvertible_items_degrade_instead_of_raising():
    hypotheses, facts, plan = _convert_findings(_findings(hypotheses=[42]))
    assert (hypotheses, facts, plan) == ([], [], None)

    hypotheses, facts, plan = _convert_findings(
        _findings(plan={"diagnosis_steps": [[1, 2]]})
    )
    assert (hypotheses, facts, plan) == ([], [], None)


def test_rca_shape_raw_strings_degrade_instead_of_raising():
    # The exact incident shape, bypassing submit_findings coercion.
    hypotheses, facts, plan = _convert_findings(
        _findings(
            hypotheses=["a string hypothesis"],
            facts=["a string fact"],
            plan={"diagnosis_steps": ["a string step"]},
        )
    )
    assert (hypotheses, facts, plan) == ([], [], None)


async def test_rca_regression_end_to_end_coercion_then_conversion():
    # Submitted through the tool, the incident shape must coerce cleanly and
    # convert to models without degrading.
    submit, state = _submit_tool()
    await _invoke(
        submit,
        hypotheses='["the device did not respond"]',
        facts='["hash not found in org"]',
        plan='{"diagnosis_steps": ["retry with a narrower query"]}',
    )
    hypotheses, facts, plan = _convert_findings(state.findings)
    assert hypotheses[0].summary == "the device did not respond"
    assert facts[0].value == "hash not found in org"
    assert plan is not None
    assert plan.diagnosis_steps[0].description == "retry with a narrower query"
