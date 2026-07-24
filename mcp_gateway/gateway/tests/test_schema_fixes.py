"""Generic schema-fix contract tests.

The critical guarantee pinned here: the gateway NEVER validates appliance
responses. Vendor response schemas mis-declare reality (Springfox omits
nullability), and FastMCP's output validation discards a valid 200 payload
whole on the first mismatch ("Output validation error: None is not of type
'integer'" — observed live on FortiEDR /api/incidents). Responses are
evidence; they must pass through verbatim.
"""

import asyncio

from gateway.schema_fixes import apply_fixes


def _mini_spec(responses):
    return {
        "openapi": "3.0.3",
        "info": {"title": "t", "version": "1"},
        "paths": {
            "/thing": {
                "get": {
                    "operationId": "get_thing",
                    "responses": responses,
                }
            }
        },
    }


def test_apply_fixes_strips_openapi3_response_content():
    spec = apply_fixes(_mini_spec({
        "200": {
            "description": "OK",
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    }))
    resp = spec["paths"]["/thing"]["get"]["responses"]["200"]
    assert "content" not in resp
    assert resp["description"] == "OK"
    assert spec["paths"]["/thing"]["get"]["operationId"] == "get_thing"


def test_apply_fixes_strips_swagger2_response_schema():
    spec = apply_fixes(_mini_spec({
        "200": {"description": "OK", "schema": {"type": "object"}}
    }))
    resp = spec["paths"]["/thing"]["get"]["responses"]["200"]
    assert "schema" not in resp
    assert resp["description"] == "OK"


def test_built_gateway_tools_have_no_output_schema():
    """End-to-end: no tool built from any pack advertises an output schema,
    so FastMCP performs no output validation. Catches regressions from a
    fastmcp upgrade or a pack hook reintroducing response schemas."""
    from gateway.app import build_gateway

    gateway = build_gateway()
    tools = asyncio.run(gateway.get_tools())
    offenders = [
        name for name, tool in tools.items()
        if tool.output_schema is not None
        # get_inventory_tree is gateway-native Python (-> str); its schema
        # derives from our own signature, not a vendor spec — cannot mismatch.
        and not name.endswith("_get_inventory_tree")
    ]
    assert not offenders, f"{len(offenders)} tools advertise output schemas: {offenders[:10]}"
