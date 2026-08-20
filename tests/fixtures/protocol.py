"""Helpers for speaking the single supported revision, ``2026-07-28``.

Every request must carry a ``_meta`` block and the mirrored ``MCP-Protocol-Version``
/ ``Mcp-Method`` / ``Mcp-Name`` headers. :class:`MCPTestClient` fills in whatever a
test did not spell out, so each test stays about the behaviour it exercises rather
than about the envelope. Conformance tests for the envelope itself use a plain
``TestClient`` and build every field by hand.
"""

from copy import deepcopy
from typing import Any

from starlette.testclient import TestClient

from http_mcp._mcp_types.meta import (
    META_CLIENT_CAPABILITIES,
    META_PROTOCOL_VERSION,
    META_SERVER_INFO,
)
from http_mcp._mcp_types.versions import LATEST_PROTOCOL_VERSION
from http_mcp.server import DEFAULT_CACHE_TTL_MS

# Methods whose subject is mirrored into `Mcp-Name`.
_NAMED_METHODS = ("tools/call", "prompts/get")


def request_meta(
    version: str = LATEST_PROTOCOL_VERSION,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the ``_meta`` block a request carries."""
    return {
        META_PROTOCOL_VERSION: version,
        META_CLIENT_CAPABILITIES: capabilities if capabilities is not None else {},
    }


def with_envelope(
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Complete a request body and header set, leaving anything explicit untouched."""
    body = deepcopy(body)
    headers = dict(headers or {})
    method = body.get("method")
    if not isinstance(method, str):
        return body, headers

    params = body.get("params")
    if not isinstance(params, dict):
        params = {}
        body["params"] = params
    params.setdefault("_meta", request_meta())

    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("MCP-Protocol-Version", LATEST_PROTOCOL_VERSION)
    headers.setdefault("Mcp-Method", method)
    name = params.get("name")
    if method in _NAMED_METHODS and isinstance(name, str):
        headers.setdefault("Mcp-Name", name)
    return body, headers


def result_envelope(
    name: str = "test",
    version: str = "1.0.0",
    *,
    cacheable: bool = False,
    ttl_ms: int = DEFAULT_CACHE_TTL_MS,
    cache_scope: str = "public",
) -> dict[str, Any]:
    """Build the protocol fields every result carries, for exact-match assertions."""
    envelope: dict[str, Any] = {
        "resultType": "complete",
        "_meta": {META_SERVER_INFO: {"name": name, "version": version}},
    }
    if cacheable:
        envelope["ttlMs"] = ttl_ms
        envelope["cacheScope"] = cache_scope
    return envelope


_ENVELOPE_KEYS = ("resultType", "_meta", "ttlMs", "cacheScope")


def without_envelope(message: dict[str, Any]) -> dict[str, Any]:
    """Return a response with the protocol result fields stripped out.

    The envelope has its own conformance tests in ``test_protocol_2026_07_28``;
    dropping it here keeps these assertions about the payload they are testing.
    """
    stripped = deepcopy(message)
    result = stripped.get("result")
    if isinstance(result, dict):
        for key in _ENVELOPE_KEYS:
            result.pop(key, None)
    return stripped


class MCPTestClient(TestClient):
    """``TestClient`` that completes the request envelope for MCP posts.

    Pass ``raw=True`` to send exactly what the test provides, which is what the
    tests for malformed requests need.
    """

    def post(  # type: ignore[override]
        self,
        url: str,
        *,
        json: Any = None,  # noqa: ANN401
        headers: dict[str, str] | None = None,
        raw: bool = False,
        **kwargs: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """Post ``json`` to ``url`` with the envelope filled in."""
        if raw or not isinstance(json, dict):
            return super().post(url, json=json, headers=headers, **kwargs)
        body, complete_headers = with_envelope(json, headers)
        return super().post(url, json=body, headers=complete_headers, **kwargs)
