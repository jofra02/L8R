"""search_tool_catalog parameter rendering (no DB, no network, no LLM).

The catalog output is the ONLY place the agent sees a tool's contract before
calling it — types, formats, enums, and required flags must survive into the
rendered text, or the agent guesses argument formats and burns tool cycles on
appliance 400s (observed live: ISO dates against epoch-millis params,
invented enum casings). Token discipline: one line per parameter, enum display
capped.

Run: uv run pytest src/testing/test_catalog_param_render.py
"""

from src.agents.engineer_tools import _ENUM_DISPLAY_CAP, _render_param_lines


def test_enum_type_and_required_are_rendered():
    schema = {
        "properties": {
            "timeFilter": {
                "type": "string",
                "enum": ["Last7days", "All", "Custom"],
                "description": "Time window",
            },
            "startDate": {
                "type": "integer",
                "format": "int64",
                "description": "Epoch milliseconds",
            },
        },
        "required": ["timeFilter"],
    }
    lines = _render_param_lines(schema)

    assert lines[0] == "Parameters:"
    assert (
        "  - timeFilter (REQUIRED) [string, one of: Last7days|All|Custom]: "
        "Time window" in lines
    )
    assert "  - startDate [integer (int64)]: Epoch milliseconds" in lines


def test_array_item_type_is_rendered():
    schema = {
        "properties": {
            "incidentIds": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Incident ids",
            },
        },
    }
    lines = _render_param_lines(schema)
    assert "  - incidentIds [array of integer]: Incident ids" in lines


def test_enum_display_is_capped():
    values = [f"v{i}" for i in range(_ENUM_DISPLAY_CAP + 5)]
    schema = {"properties": {"p": {"type": "string", "enum": values, "description": "d"}}}
    (_, line) = _render_param_lines(schema)
    assert f"|... +5 more" in line
    assert values[_ENUM_DISPLAY_CAP - 1] in line
    assert values[_ENUM_DISPLAY_CAP] not in line


def test_typeless_shell_degrades_to_name_and_description():
    # Pre-migration payloads carry anyOf shells without type/enum — the render
    # must not crash and must still show name + description/title.
    schema = {
        "properties": {
            "timeFilter": {"anyOf": [{}, {"type": "null"}], "title": "Timefilter"},
        },
    }
    lines = _render_param_lines(schema)
    assert "  - timeFilter: Timefilter" in lines


def test_empty_schema_renders_nothing():
    assert _render_param_lines({}) == []
    assert _render_param_lines({"properties": {}}) == []
