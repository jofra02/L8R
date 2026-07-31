"""Unit tests for RoutingClient request/response-shaping helpers.

These cover the generic rewriting done around an appliance call, independent
of tenant/device resolution (which needs a live registry). The
blank-query-param strip exists because FastMCP's OpenAPI layer serializes
unset optional query params as ``name=`` (blank), which the Fortinet REST
APIs reject with HTTP 400 / server-side SQL errors instead of applying their
own defaults. The UTF-8 repair exists because appliances emit stored text
fields verbatim: a Latin-1 byte (accented character in a FortiCare company
name) makes the JSON body invalid UTF-8 and crashes
``httpx.Response.json()`` inside FastMCP.
"""

import httpx

from gateway.routing_client import (
    _repair_mixed_utf8,
    _repair_response_encoding,
    _strip_blank_query_params,
)


def _query_of(url: str) -> dict:
    req = httpx.Request("GET", url)
    _strip_blank_query_params(req)
    return dict(req.url.params.multi_items())


def test_blank_params_dropped_values_kept():
    q = _query_of("https://h/api/incidents?typeFilter=&pageSize=100&timeFilter=&offset=0")
    assert q == {"pageSize": "100", "offset": "0"}


def test_all_blank_clears_query_string():
    req = httpx.Request("GET", "https://h/api/x?a=&b=")
    _strip_blank_query_params(req)
    assert req.url.query == b""
    assert str(req.url) == "https://h/api/x"


def test_no_blanks_is_noop():
    q = _query_of("https://h/api/x?a=1&b=two")
    assert q == {"a": "1", "b": "two"}


def test_no_query_is_noop():
    req = httpx.Request("GET", "https://h/api/x")
    _strip_blank_query_params(req)
    assert str(req.url) == "https://h/api/x"


def test_repeated_param_only_blank_dropped():
    # A repeated key keeps its non-blank occurrences.
    q = httpx.Request("GET", "https://h/api/x?tag=&tag=prod&tag=")
    _strip_blank_query_params(q)
    assert q.url.params.multi_items() == [("tag", "prod")]


# ---------------------------------------------------------------------------
# UTF-8 body repair
# ---------------------------------------------------------------------------

def test_valid_utf8_body_untouched():
    assert _repair_mixed_utf8('{"a": "ñ ✓"}'.encode("utf-8")) is None


def test_lone_latin1_byte_repaired():
    assert _repair_mixed_utf8(b'{"a": "Garc\xeda"}') == '{"a": "García"}'.encode("utf-8")


def test_mixed_latin1_and_multibyte_utf8_preserved():
    # Legitimate multi-byte UTF-8 (✓) must survive; a whole-body Latin-1
    # re-decode would mojibake it.
    fixed = _repair_mixed_utf8(b'{"a": "Compa\xf1\xeda \xe2\x9c\x93"}')
    assert fixed == '{"a": "Compañía ✓"}'.encode("utf-8")


def test_consecutive_and_trailing_invalid_bytes():
    assert _repair_mixed_utf8(b"\xed\xfa") == "íú".encode("utf-8")


def test_non_json_content_type_untouched():
    resp = httpx.Response(200, content=b"Garc\xed", headers={"content-type": "text/plain"})
    _repair_response_encoding(resp)
    assert resp.content == b"Garc\xed"


def test_json_response_repaired_in_place():
    resp = httpx.Response(
        200,
        content=b'{"a": "Garc\xeda"}',
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "https://10.0.0.1/api/v2/monitor/license/status"),
    )
    _repair_response_encoding(resp)
    assert resp.json() == {"a": "García"}
