from http import HTTPStatus

from starlette.testclient import TestClient

from http_mcp._transport_types import ProtocolErrorCode
from tests.models import DUMMY_SERVER


def test_unsupported_content_type() -> None:
    client = TestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert response.json() == {
        "jsonrpc": "2.0",
        "error": {
            "code": ProtocolErrorCode.INVALID_PARAMS.value,
            "message": "Unsupported Media Type: Content-Type must be application/json",
        },
    }


def test_unsupported_request_method() -> None:
    client = TestClient(DUMMY_SERVER.app)

    response = client.get("/mcp")
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert response.text == "Method Not Allowed"


def test_request_body_too_large() -> None:
    client = TestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1,
        },
        content=b"a" * 5 * 1024 * 1024,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert response.json() == {
        "jsonrpc": "2.0",
        "error": {
            "code": ProtocolErrorCode.INVALID_PARAMS.value,
            "message": "Request body too large.",
        },
    }


def test_parse_error() -> None:
    client = TestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        content=b"invalid",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {
        "jsonrpc": "2.0",
        "error": {
            "code": ProtocolErrorCode.INVALID_PARAMS.value,
            "message": "Parse error: Invalid body",
        },
    }


def test_notification() -> None:
    client = TestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        },
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.text == ""


def test_invalid_message() -> None:
    client = TestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0"},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {
        "jsonrpc": "2.0",
        "error": {
            "code": ProtocolErrorCode.METHOD_NOT_FOUND.value,
            "message": "Error validating message request",
        },
    }
