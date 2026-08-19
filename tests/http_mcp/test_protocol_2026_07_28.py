"""Conformance tests for MCP revision 2026-07-28 (the stateless, modern era)."""

import asyncio
import json
from base64 import b64encode
from http import HTTPStatus
from typing import Any

import pytest
from pydantic import BaseModel, Field
from starlette.testclient import TestClient

from http_mcp._json_rcp_types.errors import ErrorCode
from http_mcp._mcp_types.versions import (
    LATEST_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
)
from http_mcp.server import DEFAULT_CACHE_TTL_MS, MCPServer
from http_mcp.types import Arguments, Tool
from tests.fixtures.main import mcp_server, mount_mcp_server
from tests.fixtures.models import DUMMY_SERVER

V = LATEST_PROTOCOL_VERSION


def meta(
    version: str = V,
    *,
    capabilities: dict[str, Any] | None = {},  # noqa: B006
    client_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the `_meta` block a modern request carries."""
    block: dict[str, Any] = {}
    if version is not None:
        block["io.modelcontextprotocol/protocolVersion"] = version
    if capabilities is not None:
        block["io.modelcontextprotocol/clientCapabilities"] = capabilities
    if client_info is not None:
        block["io.modelcontextprotocol/clientInfo"] = client_info
    return block


def headers(method: str, name: str | None = None, version: str = V, **extra: str) -> dict[str, str]:
    """Build the mirrored request-metadata headers for a modern POST."""
    built = {
        "Content-Type": "application/json",
        "MCP-Protocol-Version": version,
        "Mcp-Method": method,
    }
    if name is not None:
        built["Mcp-Name"] = name
    built.update(extra)
    return built


def sentinel(value: str) -> str:
    """Wrap a value in the Base64 sentinel format clients use for unsafe values."""
    return f"=?base64?{b64encode(value.encode('utf-8')).decode('ascii')}?="


def client() -> TestClient:
    return TestClient(mount_mcp_server(mcp_server))


# ---------------------------------------------------------------------------
# server/discover
# ---------------------------------------------------------------------------


def test_discover_advertises_versions_capabilities_and_identity() -> None:
    response = client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": meta()}},
        headers=headers("server/discover"),
    )

    assert response.status_code == HTTPStatus.OK
    result = response.json()["result"]
    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == list(SUPPORTED_PROTOCOL_VERSIONS)
    assert result["supportedVersions"][0] == V
    assert result["capabilities"] == {
        "prompts": {"listChanged": False},
        "tools": {"listChanged": False},
    }
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"] == {
        "name": "test",
        "version": "1.0.0",
    }
    assert result["ttlMs"] == DEFAULT_CACHE_TTL_MS
    assert result["cacheScope"] == "private"


def test_discover_reports_instructions_when_configured() -> None:
    server = MCPServer("test", "1.0.0", instructions="Use me wisely.")
    response = TestClient(mount_mcp_server(server)).post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": meta()}},
        headers=headers("server/discover"),
    )

    assert response.json()["result"]["instructions"] == "Use me wisely."


def test_discover_without_params_is_rejected_for_missing_meta() -> None:
    response = client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
        headers=headers("server/discover"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["error"]["code"] == ErrorCode.INVALID_PARAMS.value


@pytest.mark.asyncio
async def test_discover_over_stdio() -> None:
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.fixtures.main import run_stdio; run_stdio()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, _ = await process.communicate(
        json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": meta()}},
        ).encode("utf-8"),
    )

    result = json.loads(stdout_data)["result"]
    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == list(SUPPORTED_PROTOCOL_VERSIONS)
    await process.wait()


# ---------------------------------------------------------------------------
# Per-request `_meta`
# ---------------------------------------------------------------------------


def test_missing_protocol_version_in_meta_is_invalid_params() -> None:
    response = client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {"_meta": {"io.modelcontextprotocol/clientCapabilities": {}}},
        },
        headers=headers("tools/list"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    error = response.json()["error"]
    assert error["code"] == ErrorCode.INVALID_PARAMS.value
    assert "io.modelcontextprotocol/protocolVersion" in error["message"]


def test_missing_client_capabilities_is_invalid_params() -> None:
    response = client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {"_meta": meta(capabilities=None)},
        },
        headers=headers("tools/list"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    error = response.json()["error"]
    assert error["code"] == ErrorCode.INVALID_PARAMS.value
    assert "io.modelcontextprotocol/clientCapabilities" in error["message"]


def test_client_info_is_optional() -> None:
    response = client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta()}},
        headers=headers("tools/list"),
    )

    assert response.status_code == HTTPStatus.OK
    assert "result" in response.json()


def test_unsupported_protocol_version_lists_supported_versions() -> None:
    response = client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {"_meta": meta("1900-01-01")},
        },
        headers=headers("tools/list", version="1900-01-01"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["error"] == {
        "code": ErrorCode.UNSUPPORTED_PROTOCOL_VERSION.value,
        "message": "Unsupported protocol version",
        "data": {"supported": list(SUPPORTED_PROTOCOL_VERSIONS), "requested": "1900-01-01"},
    }


def test_legacy_version_declared_in_modern_meta_is_rejected() -> None:
    """A legacy revision does not define `_meta`, so it cannot be claimed there."""
    response = client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {"_meta": meta("2025-11-25")},
        },
        headers=headers("tools/list", version="2025-11-25"),
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["error"]["code"] == ErrorCode.UNSUPPORTED_PROTOCOL_VERSION.value


# ---------------------------------------------------------------------------
# Result shape: resultType, serverInfo, caching hints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["tools/list", "prompts/list"])
def test_list_results_carry_caching_hints(method: str) -> None:
    response = client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": {"_meta": meta()}},
        headers=headers(method),
    )

    result = response.json()["result"]
    assert result["resultType"] == "complete"
    assert result["ttlMs"] == DEFAULT_CACHE_TTL_MS
    assert result["cacheScope"] == "private"
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "test"


def test_tools_call_result_is_not_cacheable() -> None:
    response = client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_time", "arguments": {}, "_meta": meta()},
        },
        headers=headers("tools/call", "get_time"),
    )

    result = response.json()["result"]
    assert result["resultType"] == "complete"
    assert "ttlMs" not in result
    assert "cacheScope" not in result
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["version"] == "1.0.0"


def test_prompts_get_result_carries_result_type() -> None:
    response = client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "prompts/get",
            "params": {"name": "get_advice_without_arguments", "_meta": meta()},
        },
        headers=headers("prompts/get", "get_advice_without_arguments"),
    )

    result = response.json()["result"]
    assert result["resultType"] == "complete"
    assert result["messages"]
    assert "ttlMs" not in result


def test_errors_do_not_carry_result_type() -> None:
    response = client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "not_found", "arguments": {}, "_meta": meta()},
        },
        headers=headers("tools/call", "not_found"),
    )

    body = response.json()
    assert "result" not in body
    assert body["error"]["code"] == ErrorCode.INVALID_PARAMS.value


def test_legacy_results_omit_modern_fields() -> None:
    """Legacy revisions define none of resultType, _meta, ttlMs or cacheScope."""
    response = client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Content-Type": "application/json"},
    )

    result = response.json()["result"]
    assert result["tools"]
    for field in ("resultType", "_meta", "ttlMs", "cacheScope"):
        assert field not in result


# ---------------------------------------------------------------------------
# Removed methods
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["ping", "initialize"])
def test_removed_methods_are_not_found_under_the_modern_era(method: str) -> None:
    response = client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": {"_meta": meta()}},
        headers=headers(method),
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["error"]["code"] == ErrorCode.METHOD_NOT_FOUND.value


def test_unknown_method_is_not_found_under_the_modern_era() -> None:
    response = client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"_meta": meta()}},
        headers=headers("resources/read"),
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["error"]["code"] == ErrorCode.METHOD_NOT_FOUND.value


def test_unknown_method_stays_a_bad_request_for_legacy_clients() -> None:
    response = client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "resources/read"},
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.parametrize("http_method", ["get", "delete"])
def test_get_and_delete_are_method_not_allowed(http_method: str) -> None:
    response = getattr(client(), http_method)("/mcp")

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_session_and_resumption_headers_are_ignored() -> None:
    response = client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta()}},
        headers=headers("tools/list", **{"Mcp-Session-Id": "abc", "Last-Event-ID": "7"}),
    )

    assert response.status_code == HTTPStatus.OK
    assert "mcp-session-id" not in response.headers


# ---------------------------------------------------------------------------
# Mirrored request-metadata headers
# ---------------------------------------------------------------------------


def _header_mismatch(body: dict[str, Any], sent: dict[str, str]) -> dict[str, Any]:
    response = client().post("/mcp", json=body, headers=sent)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    error = response.json()["error"]
    assert error["code"] == ErrorCode.HEADER_MISMATCH.value
    return error


def test_missing_protocol_version_header_is_a_header_mismatch() -> None:
    sent = headers("tools/list")
    del sent["MCP-Protocol-Version"]
    error = _header_mismatch(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta()}},
        sent,
    )
    assert "MCP-Protocol-Version header is required" in error["message"]


def test_protocol_version_header_must_match_the_body() -> None:
    error = _header_mismatch(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta()}},
        headers("tools/list", version="2025-11-25"),
    )
    assert "MCP-Protocol-Version" in error["message"]


def test_missing_method_header_is_a_header_mismatch() -> None:
    sent = headers("tools/list")
    del sent["Mcp-Method"]
    error = _header_mismatch(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta()}},
        sent,
    )
    assert "Mcp-Method header is required" in error["message"]


def test_method_header_must_match_the_body() -> None:
    error = _header_mismatch(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta()}},
        headers("prompts/list"),
    )
    assert "does not match" in error["message"]


@pytest.mark.parametrize(
    ("method", "name"),
    [("tools/call", "get_time"), ("prompts/get", "get_advice_without_arguments")],
)
def test_name_header_is_required_for_named_methods(method: str, name: str) -> None:
    error = _header_mismatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": {"name": name, "arguments": {}, "_meta": meta()},
        },
        headers(method),
    )
    assert "Mcp-Name header is required" in error["message"]


def test_name_header_accepts_the_base64_sentinel() -> None:
    response = client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_time", "arguments": {}, "_meta": meta()},
        },
        headers=headers("tools/call", sentinel("get_time")),
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["result"]["isError"] is False


def test_name_header_rejects_a_malformed_sentinel() -> None:
    error = _header_mismatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_time", "arguments": {}, "_meta": meta()},
        },
        headers("tools/call", "=?base64?not!valid!?="),
    )
    assert "not a valid header value" in error["message"]


def test_legacy_requests_are_not_header_validated() -> None:
    """A 2025-era client sends none of these headers and must still be served."""
    response = client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_time", "arguments": {}},
        },
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["result"]["isError"] is False


# ---------------------------------------------------------------------------
# x-mcp-header parameter mirroring
# ---------------------------------------------------------------------------


class RegionQueryInput(BaseModel):
    region: str = Field(json_schema_extra={"x-mcp-header": "Region"})
    replicas: int = Field(default=1, json_schema_extra={"x-mcp-header": "Replicas"})
    query: str


class RegionQueryOutput(BaseModel):
    executed: str


def execute_sql(args: Arguments[RegionQueryInput]) -> RegionQueryOutput:
    """Execute SQL in a region."""
    return RegionQueryOutput(executed=f"{args.inputs.region}:{args.inputs.query}")


HEADER_PARAM_SERVER = MCPServer(
    "header-params",
    "1.0.0",
    (Tool(func=execute_sql, inputs=RegionQueryInput, output=RegionQueryOutput),),
)


def call_execute_sql(arguments: dict[str, Any], **extra: str) -> Any:  # noqa: ANN401
    return TestClient(mount_mcp_server(HEADER_PARAM_SERVER)).post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "execute_sql", "arguments": arguments, "_meta": meta()},
        },
        headers=headers("tools/call", "execute_sql", **extra),
    )


def test_param_headers_matching_the_body_are_accepted() -> None:
    response = call_execute_sql(
        {"region": "us-west1", "replicas": 3, "query": "SELECT 1"},
        **{"Mcp-Param-Region": "us-west1", "Mcp-Param-Replicas": "3"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["result"]["structuredContent"] == {"executed": "us-west1:SELECT 1"}


def test_param_header_mismatching_the_body_is_rejected() -> None:
    response = call_execute_sql(
        {"region": "us-west1", "replicas": 3, "query": "SELECT 1"},
        **{"Mcp-Param-Region": "eu-west1", "Mcp-Param-Replicas": "3"},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["error"]["code"] == ErrorCode.HEADER_MISMATCH.value


def test_param_header_omitted_while_the_argument_is_present_is_rejected() -> None:
    response = call_execute_sql(
        {"region": "us-west1", "replicas": 3, "query": "SELECT 1"},
        **{"Mcp-Param-Replicas": "3"},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "Mcp-Param-region header is required" in response.json()["error"]["message"]


def test_param_header_sent_without_the_argument_is_rejected() -> None:
    response = call_execute_sql(
        {"region": "us-west1", "query": "SELECT 1"},
        **{"Mcp-Param-Region": "us-west1", "Mcp-Param-Replicas": "3"},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "has no value in the body" in response.json()["error"]["message"]


def test_integer_param_headers_compare_numerically() -> None:
    response = call_execute_sql(
        {"region": "us-west1", "replicas": 3, "query": "SELECT 1"},
        **{"Mcp-Param-Region": "us-west1", "Mcp-Param-Replicas": "3.0"},
    )

    assert response.status_code == HTTPStatus.OK


def test_param_headers_accept_the_base64_sentinel() -> None:
    response = call_execute_sql(
        {"region": "us west1", "replicas": 1, "query": "SELECT 1"},
        **{"Mcp-Param-Region": sentinel(" padded "), "Mcp-Param-Replicas": "1"},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    response = call_execute_sql(
        {"region": " padded ", "replicas": 1, "query": "SELECT 1"},
        **{"Mcp-Param-Region": sentinel(" padded "), "Mcp-Param-Replicas": "1"},
    )
    assert response.status_code == HTTPStatus.OK


def test_unannotated_param_headers_are_ignored() -> None:
    response = client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_time", "arguments": {}, "_meta": meta()},
        },
        headers=headers("tools/call", "get_time", **{"Mcp-Param-Unknown": "whatever"}),
    )

    assert response.status_code == HTTPStatus.OK


# ---------------------------------------------------------------------------
# Origin validation
# ---------------------------------------------------------------------------


def _post_with_origin(server: MCPServer, origin: str | None) -> Any:  # noqa: ANN401
    sent = headers("tools/list")
    if origin is not None:
        sent["Origin"] = origin
    return TestClient(mount_mcp_server(server)).post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta()}},
        headers=sent,
    )


def test_origin_is_unchecked_when_no_allowlist_is_configured() -> None:
    assert _post_with_origin(DUMMY_SERVER, "https://evil.example").status_code == HTTPStatus.OK


def test_disallowed_origin_is_forbidden() -> None:
    server = MCPServer("test", "1.0.0", allowed_origins=("https://app.example.com",))

    response = _post_with_origin(server, "https://evil.example")

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"]["message"] == "Origin not allowed"


def test_allowed_origin_is_served() -> None:
    server = MCPServer("test", "1.0.0", allowed_origins=("https://app.example.com",))

    assert _post_with_origin(server, "https://app.example.com").status_code == HTTPStatus.OK


def test_absent_origin_is_served_even_with_an_allowlist() -> None:
    server = MCPServer("test", "1.0.0", allowed_origins=("https://app.example.com",))

    assert _post_with_origin(server, None).status_code == HTTPStatus.OK


# ---------------------------------------------------------------------------
# Caching configuration
# ---------------------------------------------------------------------------


def test_cache_scope_defaults_to_public_without_scoped_features() -> None:
    assert MCPServer("test", "1.0.0").cache_scope == "public"


def test_cache_scope_defaults_to_private_with_scoped_features() -> None:
    assert mcp_server.cache_scope == "private"


def test_cache_settings_can_be_overridden() -> None:
    server = MCPServer("test", "1.0.0", cache_ttl_ms=0, cache_scope="public")

    response = TestClient(mount_mcp_server(server)).post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta()}},
        headers=headers("tools/list"),
    )

    result = response.json()["result"]
    assert result["ttlMs"] == 0
    assert result["cacheScope"] == "public"


def test_negative_cache_ttl_is_rejected() -> None:
    with pytest.raises(ValueError, match="cache_ttl_ms"):
        MCPServer("test", "1.0.0", cache_ttl_ms=-1)


# ---------------------------------------------------------------------------
# Pagination alongside `_meta`
# ---------------------------------------------------------------------------


def test_pagination_cursor_coexists_with_request_meta() -> None:
    """`_meta` rides in the same params object as a method's own fields."""
    response = client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {"cursor": "0", "_meta": meta()},
        },
        headers=headers("tools/list"),
    )

    assert response.status_code == HTTPStatus.OK
    result = response.json()["result"]
    assert result["tools"]
    assert result["resultType"] == "complete"


def test_invalid_cursor_is_still_rejected_under_the_modern_era() -> None:
    response = client().post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {"cursor": "not_a_number", "_meta": meta()},
        },
        headers=headers("tools/list"),
    )

    body = response.json()
    assert "result" not in body
    assert body["error"]["code"] == ErrorCode.INVALID_PARAMS.value
