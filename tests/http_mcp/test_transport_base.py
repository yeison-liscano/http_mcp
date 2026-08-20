from http import HTTPStatus

import pytest
from starlette.requests import Request

from http_mcp._json_rcp_types.errors import ErrorCode
from http_mcp._json_rcp_types.messages import JSONRPCError, JSONRPCRequest
from http_mcp._mcp_types.versions import LATEST_PROTOCOL_VERSION
from http_mcp._transport_http import HTTPTransport
from tests.fixtures.main import mcp_server, mount_mcp_server
from tests.fixtures.models import DUMMY_SERVER
from tests.fixtures.protocol import MCPTestClient, request_meta


def test_initialize_is_no_longer_a_method() -> None:
    """The handshake went away with the session concept; `initialize` is unknown now."""
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ExampleClient", "version": "1.0.0"},
            },
        },
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["error"]["code"] == ErrorCode.METHOD_NOT_FOUND.value


def test_unsupported_protocol_version_is_rejected() -> None:
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {"_meta": request_meta(version="2025-06-18")},
        },
        headers={"MCP-Protocol-Version": "2025-06-18"},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": ErrorCode.UNSUPPORTED_PROTOCOL_VERSION.value,
            "message": "Unsupported protocol version",
            "data": {
                "supported": [LATEST_PROTOCOL_VERSION],
                "requested": "2025-06-18",
            },
        },
    }


def test_method_not_found() -> None:
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "invalid", "id": 1},
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": ErrorCode.METHOD_NOT_FOUND.value,
            "message": "Error validating message request",
        },
    }


def test_invalid_tool_execution_request() -> None:
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {"name": "dummy_tool", "arguments": "not-a-mapping"},
        },
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": '[{"field": "params.arguments", "message": "Input should be a valid'
            ' dictionary"}]',
        },
    }


def test_prompts_get_with_invalid_arguments_returns_invalid_params() -> None:
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "prompts/get",
            "params": {"name": "whatever", "arguments": "not-a-mapping"},
        },
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["error"]["code"] == ErrorCode.INVALID_PARAMS.value


def test_prompts_get_without_arguments_key_defaults_to_empty() -> None:
    client = MCPTestClient(mount_mcp_server(mcp_server))

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "prompts/get",
            "params": {"name": "get_advice_without_arguments"},
        },
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert "result" in body
    assert body["result"]["messages"]


def test_tools_call_without_arguments_key_defaults_to_empty() -> None:
    client = MCPTestClient(mount_mcp_server(mcp_server))

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_time"},
        },
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert "result" in body
    assert body["result"]["isError"] is False


def test_tools_list_with_invalid_cursor_returns_invalid_params() -> None:
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/list",
            "params": {"cursor": "not_a_number"},
        },
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["error"]["code"] == ErrorCode.INVALID_PARAMS.value


@pytest.mark.asyncio
async def test_unhandled_method_fails_closed() -> None:
    """A method with no handler must 404, not fall through to some default.

    `model_construct` bypasses validation the way a future widening of the method
    literal would: the guard exists so that adding a method without wiring a handler
    is a visible 404 rather than silent, unspecified behaviour.
    """
    transport = HTTPTransport(DUMMY_SERVER)
    message = JSONRPCRequest.model_construct(
        jsonrpc="2.0",
        id=1,
        method="resources/read",
        params={"_meta": request_meta()},
    )

    response, status = await transport._process_request(  # noqa: SLF001
        message,
        Request({"type": "http", "method": "POST", "headers": [], "path": "/"}),
    )

    assert status == HTTPStatus.NOT_FOUND
    assert isinstance(response, JSONRPCError)
    assert response.error.code == ErrorCode.METHOD_NOT_FOUND
    assert response.error.message == "Method not supported: resources/read"
