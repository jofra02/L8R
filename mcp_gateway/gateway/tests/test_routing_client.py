"""Unit tests for RoutingClient request-shaping helpers.

These cover the generic request rewriting done before a request reaches an
appliance, independent of tenant/device resolution (which needs a live
registry). The blank-query-param strip exists because FastMCP's OpenAPI layer
serializes unset optional query params as ``name=`` (blank), which the Fortinet
REST APIs reject with HTTP 400 / server-side SQL errors instead of applying
their own defaults.
"""

import httpx

from gateway.routing_client import _strip_blank_query_params


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
