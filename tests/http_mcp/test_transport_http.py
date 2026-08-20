from http import HTTPStatus
from typing import Any

import pytest
from starlette.requests import Request
from starlette.types import Message

from http_mcp import _transport_http
from http_mcp._json_rcp_types.errors import ErrorCode
from http_mcp._mcp_types.versions import LATEST_PROTOCOL_VERSION
from http_mcp._transport_http import MAXIMUM_MESSAGE_SIZE
from http_mcp.server import MCPServer
from tests.fixtures.models import DUMMY_SERVER, DUMMY_TOOL
from tests.fixtures.protocol import MCPTestClient


def test_unsupported_content_type() -> None:
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert response.json() == {
        "jsonrpc": "2.0",
        "error": {
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": "Unsupported Media Type: Content-Type must be application/json",
        },
    }


def test_unsupported_request_method() -> None:
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.get("/mcp")
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert response.text == "Method Not Allowed"


def test_request_body_too_large() -> None:
    client = MCPTestClient(DUMMY_SERVER.app)

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
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": "Request body too large.",
        },
    }


def test_parse_error() -> None:
    client = MCPTestClient(DUMMY_SERVER.app)

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
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": "Parse error: Invalid body",
        },
    }


def test_unknown_notification_is_not_found() -> None:
    """Revision 2026-07-28 defines no notifications, so none are accepted.

    `notifications/initialized` went away with the `initialize` handshake. Taking a
    202 for any string under the prefix also let a notification skip the mirrored
    header check that every other request has to pass.
    """
    client = MCPTestClient(DUMMY_SERVER.app)

    for method in ("notifications/initialized", "notifications/made/up/xyz"):
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": method},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json()["error"]["code"] == ErrorCode.METHOD_NOT_FOUND.value


def test_retired_method_is_not_found() -> None:
    """`ping` and `initialize` went away with the session concept."""
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": "1", "method": "ping"},
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": "1",
        "error": {
            "code": ErrorCode.METHOD_NOT_FOUND.value,
            "message": "Error validating message request",
        },
    }


def test_body_without_a_method_fails_the_envelope_check() -> None:
    """`Mcp-Method` mirrors the body method, so a body with none cannot agree with it."""
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.post("/mcp", json={"jsonrpc": "2.0"})
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["error"]["code"] == ErrorCode.HEADER_MISMATCH.value


def test_json_array_body_returns_invalid_request() -> None:
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}],
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json() == {
        "jsonrpc": "2.0",
        "error": {
            "code": ErrorCode.INVALID_REQUEST.value,
            "message": "Invalid Request: body must be a single JSON-RPC request object",
        },
    }


def test_json_scalar_body_returns_invalid_request() -> None:
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json="just a string",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["error"]["code"] == ErrorCode.INVALID_REQUEST.value


def test_notification_method_with_id_returns_method_not_found() -> None:
    client = MCPTestClient(DUMMY_SERVER.app)

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 6, "method": "notifications/subscribe"},
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 6,
        "error": {
            "code": ErrorCode.METHOD_NOT_FOUND.value,
            "message": "Error validating message request",
        },
    }


# ---------------------------------------------------------------------------
# Request body limit
# ---------------------------------------------------------------------------


async def _post_streamed(server: MCPServer, body: bytes, chunk_size: int) -> dict[str, Any]:
    """Drive the ASGI app directly, recording how much of the body it consumed.

    `TestClient` hands the whole body over at once, which is exactly the detail under
    test: the limit has to be applied while reading, so the interesting number is how
    many bytes the server accepted before it answered.
    """
    chunks = [body[i : i + chunk_size] for i in range(0, len(body), chunk_size)] or [b""]
    state = {"index": 0, "delivered": 0}
    sent: list[Message] = []

    async def receive() -> Message:
        index = state["index"]
        if index >= len(chunks):
            return {"type": "http.disconnect"}
        state["index"] += 1
        state["delivered"] += len(chunks[index])
        return {
            "type": "http.request",
            "body": chunks[index],
            "more_body": index + 1 < len(chunks),
        }

    async def send(message: Message) -> None:
        sent.append(message)

    await server.app(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "root_path": "",
            "scheme": "http",
            "http_version": "1.1",
            "query_string": b"",
            "client": ("1.2.3.4", 1),
            "server": ("testserver", 80),
            "headers": [
                (b"content-type", b"application/json"),
                (b"mcp-protocol-version", LATEST_PROTOCOL_VERSION.encode()),
                (b"mcp-method", b"tools/list"),
            ],
        },
        receive,
        send,
    )
    return {"status": sent[0]["status"], "delivered": state["delivered"]}


@pytest.mark.asyncio
async def test_oversized_body_is_not_fully_buffered() -> None:
    """The 4 MB cap bounds what is read, not just what is parsed.

    Reading the whole body first and measuring afterwards lets a request cost the
    server what the client asked for rather than what the server allows.
    """
    oversized = b'{"padding":"' + b"A" * (MAXIMUM_MESSAGE_SIZE * 2) + b'"}'
    result = await _post_streamed(DUMMY_SERVER, oversized, chunk_size=64 * 1024)

    assert result["status"] == HTTPStatus.REQUEST_ENTITY_TOO_LARGE.value
    delivered = result["delivered"]
    assert isinstance(delivered, int)
    assert delivered <= MAXIMUM_MESSAGE_SIZE + 64 * 1024
    assert delivered < len(oversized)


@pytest.mark.asyncio
async def test_oversized_content_length_is_refused_before_reading() -> None:
    """A body that announces itself as too large is rejected without being read."""
    server = DUMMY_SERVER
    sent: list[Message] = []
    read = {"calls": 0}

    async def receive() -> Message:
        read["calls"] += 1
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    await server.app(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "root_path": "",
            "scheme": "http",
            "http_version": "1.1",
            "query_string": b"",
            "client": ("1.2.3.4", 1),
            "server": ("testserver", 80),
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(MAXIMUM_MESSAGE_SIZE + 1).encode()),
                (b"mcp-protocol-version", LATEST_PROTOCOL_VERSION.encode()),
                (b"mcp-method", b"tools/list"),
            ],
        },
        receive,
        send,
    )

    assert sent[0]["status"] == HTTPStatus.REQUEST_ENTITY_TOO_LARGE.value
    assert read["calls"] == 0


# ---------------------------------------------------------------------------
# Origin allowlist
# ---------------------------------------------------------------------------


def _tools_list(client: MCPTestClient, **headers: str) -> int:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=headers or None,
    )
    return response.status_code


def test_missing_origin_is_allowed_by_default() -> None:
    """Browsers always send `Origin` on a POST, so absence means a non-browser client."""
    server = MCPServer("test", "1.0.0", allowed_origins=("https://app.example",))
    client = MCPTestClient(server.app)

    assert _tools_list(client) == HTTPStatus.OK
    assert _tools_list(client, Origin="https://app.example") == HTTPStatus.OK
    assert _tools_list(client, Origin="https://evil.example") == HTTPStatus.FORBIDDEN


def test_require_origin_refuses_a_request_with_no_origin() -> None:
    """`require_origin` makes the allowlist mandatory rather than advisory."""
    server = MCPServer(
        "test",
        "1.0.0",
        allowed_origins=("https://app.example",),
        require_origin=True,
    )
    client = MCPTestClient(server.app)

    assert _tools_list(client) == HTTPStatus.FORBIDDEN
    assert _tools_list(client, Origin="https://app.example") == HTTPStatus.OK
    assert _tools_list(client, Origin="https://evil.example") == HTTPStatus.FORBIDDEN


def test_require_origin_does_nothing_without_an_allowlist() -> None:
    server = MCPServer("test", "1.0.0", require_origin=True)
    client = MCPTestClient(server.app)

    assert _tools_list(client) == HTTPStatus.OK


# ---------------------------------------------------------------------------
# Notifications still have to pass the mirrored header check
# ---------------------------------------------------------------------------


def test_a_known_notification_is_accepted_and_still_header_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 202 sits below header validation, not above it.

    Revision 2026-07-28 defines no notifications, so this pins the behaviour a future
    one would get: accepted, but only after the same header check every other request
    passes. Short-circuiting to 202 first was the one way around that check.
    """
    method = "notifications/progress"
    monkeypatch.setattr(_transport_http, "KNOWN_NOTIFICATIONS", frozenset({method}))
    client = MCPTestClient(DUMMY_SERVER.app)

    accepted = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": method},
        headers={"Content-Type": "application/json", "Mcp-Method": method},
    )
    assert accepted.status_code == HTTPStatus.ACCEPTED
    assert accepted.text == ""

    mismatched = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": method},
        headers={"Content-Type": "application/json", "Mcp-Method": "tools/call"},
        raw=False,
    )
    assert mismatched.status_code == HTTPStatus.BAD_REQUEST
    assert mismatched.json()["error"]["code"] == ErrorCode.HEADER_MISMATCH.value

    missing_header = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": method},
        headers={
            "Content-Type": "application/json",
            "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
        },
        raw=True,
    )
    assert missing_header.status_code == HTTPStatus.BAD_REQUEST
    assert missing_header.json()["error"]["code"] == ErrorCode.HEADER_MISMATCH.value


# ---------------------------------------------------------------------------
# A schema the transport cannot check is refused, not served
# ---------------------------------------------------------------------------


def test_colliding_tool_schema_is_refused_by_the_transport() -> None:
    """`MCPServer` rejects these at construction; a custom server may not.

    The transport is the last line here, so it fails closed rather than serving the
    call with one of the two annotations silently unenforced.
    """
    colliding = {
        "properties": {
            "tenant": {"type": "string", "x-mcp-header": "tenant"},
            "account": {"type": "string", "x-mcp-header": "Tenant"},
        },
    }

    class CollidingServer(MCPServer):
        def get_tool_input_schema(self, tool_name: str, request: Request) -> dict | None:  # noqa: ARG002
            return colliding

    server = CollidingServer("test", "1.0.0", (DUMMY_TOOL,))
    client = MCPTestClient(server.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "dummy_tool", "arguments": {"tenant": "acme"}},
        },
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["error"]["code"] == ErrorCode.HEADER_MISMATCH.value
    assert "duplicate x-mcp-header" in response.json()["error"]["message"]
