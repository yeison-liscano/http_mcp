from http import HTTPStatus

from starlette.testclient import TestClient

from http_mcp._json_rcp_types.errors import ErrorCode
from tests.fixtures.main import mcp_server, mount_mcp_server
from tests.fixtures.models import DUMMY_SERVER


def test_initialize_bad_request() -> None:
    client = TestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
            },
        },
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": '[{"field": "params.clientInfo", "message": "Field required"}, '
            '{"field": "params.capabilities", "message": "Field required"}]',
        },
    }


def test_initialize_unsupported_version() -> None:
    client = TestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "roots": {
                        "listChanged": True,
                    },
                    "sampling": {},
                    "elicitation": {},
                },
                "clientInfo": {
                    "name": "ExampleClient",
                    "title": "Example Client Display Name",
                    "version": "1.0.0",
                },
            },
        },
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": "Unsupported protocol version",
            "data": {
                "supported": ["2025-03-26", "2025-06-18", "2025-11-25"],
                "requested": "2024-11-05",
            },
        },
    }


def test_method_not_found() -> None:
    client = TestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "invalid", "id": 1},
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": ErrorCode.METHOD_NOT_FOUND.value,
            "message": "Error validating message request",
        },
    }


def test_invalid_tool_execution_request() -> None:
    client = TestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
        },
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": '[{"field": "params", "message": "Input should be a valid dictionary'
            ' or instance of ToolsCallRequestParams"}]',
        },
    }


def test_prompts_get_with_missing_params_returns_invalid_params() -> None:
    client = TestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "prompts/get"},
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 2,
        "error": {
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": '[{"field": "params", "message": "Input should be a valid dictionary'
            ' or instance of PromptGetRequestParams"}]',
        },
    }


def test_prompts_get_without_arguments_key_defaults_to_empty() -> None:
    client = TestClient(mount_mcp_server(mcp_server))

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "prompts/get",
            "params": {"name": "get_advice_without_arguments"},
        },
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert "result" in body
    assert body["result"]["messages"]


def test_tools_call_without_arguments_key_defaults_to_empty() -> None:
    client = TestClient(mount_mcp_server(mcp_server))

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_time"},
        },
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert "result" in body
    assert body["result"]["isError"] is False


def test_tools_list_with_invalid_cursor_returns_invalid_params() -> None:
    client = TestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/list",
            "params": {"cursor": "not_a_number"},
        },
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["error"]["code"] == ErrorCode.INVALID_PARAMS.value
