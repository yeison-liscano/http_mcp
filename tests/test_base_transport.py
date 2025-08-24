from http import HTTPStatus

from starlette.testclient import TestClient

from http_mcp._transport_types import ProtocolErrorCode
from tests.models import DUMMY_SERVER


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
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": ProtocolErrorCode.INVALID_PARAMS.value,
            "message": '[{"type": "missing", "loc": ["params", "clientInfo"], '
            '"msg": "Field required", "input": {"protocolVersion": '
            '"2025-06-18"}, "url": '
            '"https://errors.pydantic.dev/2.11/v/missing"}, {"type": '
            '"missing", "loc": ["params", "capabilities"], "msg": '
            '"Field required", "input": {"protocolVersion": '
            '"2025-06-18"}, "url": '
            '"https://errors.pydantic.dev/2.11/v/missing"}]',
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
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": ProtocolErrorCode.INVALID_PARAMS.value,
            "message": "Unsupported protocol version",
            "data": {"supported": ["2025-06-18"], "requested": "2024-11-05"},
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
            "code": ProtocolErrorCode.METHOD_NOT_FOUND.value,
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
            "code": ProtocolErrorCode.INVALID_PARAMS.value,
            "message": '[{"type": "model_type", "loc": ["params"], "msg": "Input should be a '
            'valid dictionary or instance of ToolsCallRequestParams", "input": '
            'null, "ctx": {"class_name": "ToolsCallRequestParams"}, "url": '
            '"https://errors.pydantic.dev/2.11/v/model_type"}]',
        },
    }
