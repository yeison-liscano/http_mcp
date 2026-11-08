import json
from http import HTTPStatus

import pytest
from starlette.testclient import TestClient
from starlette.types import Message

from auth_mcp.authorization_server.client_store import ClientStore, RegistrationRejected
from auth_mcp.authorization_server.registration_endpoint import (
    DynamicClientRegistrationEndpoint,
)
from auth_mcp.types.registration import ClientRegistrationRequest, ClientRegistrationResponse


class MockClientStore(ClientStore):
    def __init__(self) -> None:
        self._counter = 0

    async def register_client(
        self,
        request: ClientRegistrationRequest,
    ) -> ClientRegistrationResponse:
        self._counter += 1
        return ClientRegistrationResponse(
            client_id=f"client_{self._counter}",
            redirect_uris=request.redirect_uris,
            grant_types=request.grant_types,
            response_types=request.response_types,
            token_endpoint_auth_method=request.token_endpoint_auth_method,
        )


class RejectingClientStore(ClientStore):
    async def register_client(
        self,
        request: ClientRegistrationRequest,  # noqa: ARG002
    ) -> RegistrationRejected:
        return RegistrationRejected("Policy violation")


class CrashingClientStore(ClientStore):
    async def register_client(
        self,
        request: ClientRegistrationRequest,  # noqa: ARG002
    ) -> ClientRegistrationResponse:
        msg = "database connection lost"
        raise RuntimeError(msg)


def _create_client(
    store: ClientStore | None = None,
    allowed_custom_redirect_schemes: tuple[str, ...] = (),
) -> TestClient:
    endpoint = DynamicClientRegistrationEndpoint(
        store or MockClientStore(),
        allowed_custom_redirect_schemes=allowed_custom_redirect_schemes,
    )
    return TestClient(endpoint)


def _valid_body() -> dict[str, object]:
    return {"redirect_uris": ["https://example.com/callback"]}


def test_post_valid_registration_returns_201() -> None:
    client = _create_client()
    response = client.post("/", json=_valid_body())
    assert response.status_code == HTTPStatus.CREATED
    data = response.json()
    assert "client_id" in data
    assert data["redirect_uris"] == ["https://example.com/callback"]


def test_post_returns_json_content_type() -> None:
    client = _create_client()
    response = client.post("/", json=_valid_body())
    assert "application/json" in response.headers["content-type"]


def test_post_returns_security_headers() -> None:
    client = _create_client()
    response = client.post("/", json=_valid_body())
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "strict-transport-security" in response.headers
    assert "max-age=" in response.headers["strict-transport-security"]


def test_get_method_not_allowed() -> None:
    client = _create_client()
    response = client.get("/")
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert response.headers["allow"] == "POST"


def test_put_method_not_allowed() -> None:
    client = _create_client()
    response = client.put("/")
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_delete_method_not_allowed() -> None:
    client = _create_client()
    response = client.delete("/")
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_invalid_json_returns_400() -> None:
    client = _create_client()
    response = client.post(
        "/",
        content=b"not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    data = response.json()
    assert data["error"] == "invalid_client_metadata"


def test_wrong_content_type_returns_400() -> None:
    client = _create_client()
    response = client.post(
        "/",
        content=json.dumps(_valid_body()).encode(),
        headers={"content-type": "text/plain"},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    data = response.json()
    assert data["error"] == "invalid_client_metadata"


def test_invalid_redirect_uri_returns_400() -> None:
    client = _create_client()
    response = client.post(
        "/",
        json={"redirect_uris": ["http://not-localhost.example.com/callback"]},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    data = response.json()
    assert data["error"] == "invalid_client_metadata"


def test_missing_redirect_uris_returns_400() -> None:
    client = _create_client()
    response = client.post("/", json={})
    assert response.status_code == HTTPStatus.BAD_REQUEST
    data = response.json()
    assert data["error"] == "invalid_client_metadata"


def test_store_raises_registration_error_returns_400() -> None:
    client = _create_client(RejectingClientStore())
    response = client.post("/", json=_valid_body())
    assert response.status_code == HTTPStatus.BAD_REQUEST
    data = response.json()
    assert data["error"] == "invalid_client_metadata"
    assert "Policy violation" in data["error_description"]


def test_oversized_body_returns_413() -> None:
    client = _create_client()
    large_body = json.dumps({"redirect_uris": ["https://example.com/callback"], "x": "a" * 70000})
    response = client.post(
        "/",
        content=large_body.encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    data = response.json()
    assert data["error"] == "invalid_client_metadata"


async def _register_streamed(
    chunks: int,
    chunk: bytes,
    content_length: bytes | None = None,
) -> tuple[list[Message], int]:
    """Send a body in chunks straight to the ASGI app; report what was read."""
    endpoint = DynamicClientRegistrationEndpoint(MockClientStore())
    sent: list[Message] = []
    read = {"chunks": 0}

    async def receive() -> Message:
        read["chunks"] += 1
        return {"type": "http.request", "body": chunk, "more_body": read["chunks"] < chunks}

    async def send(message: Message) -> None:
        sent.append(message)

    headers = [(b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", content_length))
    await endpoint(
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
            "headers": headers,
        },
        receive,
        send,
    )
    return sent, read["chunks"]


@pytest.mark.asyncio
async def test_oversized_streamed_body_stops_being_read_at_the_cap() -> None:
    """The route is unauthenticated, so the cap must bound memory, not just parsing."""
    sent, chunks_read = await _register_streamed(chunks=64, chunk=b" " * 256 * 1024)

    assert sent[0]["status"] == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert chunks_read == 1


@pytest.mark.asyncio
async def test_oversized_content_length_is_refused_before_reading() -> None:
    sent, chunks_read = await _register_streamed(
        chunks=1,
        chunk=b"{}",
        content_length=str(16 * 1024 * 1024).encode(),
    )

    assert sent[0]["status"] == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert chunks_read == 0


@pytest.mark.parametrize(
    "content_type",
    [
        # CORS-safelisted types any page can send without a preflight.
        "text/plain; charset=application/json",
        "text/plain;application/json",
        "multipart/form-data; boundary=application/json",
        "application/x-www-form-urlencoded; a=application/json",
        "application/jsonx",
    ],
)
def test_content_type_must_be_application_json_itself(content_type: str) -> None:
    client = _create_client()
    response = client.post(
        "/",
        content=json.dumps(_valid_body()).encode(),
        headers={"content-type": content_type},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["error_description"] == "Content-Type must be application/json"


@pytest.mark.parametrize("content_type", ["application/json; charset=utf-8", "Application/JSON"])
def test_application_json_with_parameters_or_any_case_is_accepted(content_type: str) -> None:
    client = _create_client()
    response = client.post(
        "/",
        content=json.dumps(_valid_body()).encode(),
        headers={"content-type": content_type},
    )
    assert response.status_code == HTTPStatus.CREATED


def test_store_raises_unexpected_error_returns_500() -> None:
    client = _create_client(CrashingClientStore())
    response = client.post("/", json=_valid_body())
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    data = response.json()
    assert data["error"] == "invalid_client_metadata"
    assert "Internal server error" in data["error_description"]
    assert "database" not in response.text


def test_none_fields_excluded_from_response() -> None:
    client = _create_client()
    response = client.post("/", json=_valid_body())
    data = response.json()
    assert "client_secret" not in data
    assert "client_id_issued_at" not in data
    assert "client_secret_expires_at" not in data


def test_custom_scheme_rejected_without_allowlist() -> None:
    client = _create_client()
    response = client.post(
        "/",
        json={"redirect_uris": ["cursor://anysphere.cursor-mcp/oauth/callback"]},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    data = response.json()
    assert data["error"] == "invalid_client_metadata"


def test_custom_scheme_accepted_when_allowlisted() -> None:
    client = _create_client(allowed_custom_redirect_schemes=("cursor",))
    response = client.post(
        "/",
        json={"redirect_uris": ["cursor://anysphere.cursor-mcp/oauth/callback"]},
    )
    assert response.status_code == HTTPStatus.CREATED
    data = response.json()
    assert data["redirect_uris"] == ["cursor://anysphere.cursor-mcp/oauth/callback"]


def test_init_rejects_disallowed_scheme_in_allowlist() -> None:
    with pytest.raises(ValueError, match="must not include disallowed schemes"):
        DynamicClientRegistrationEndpoint(
            MockClientStore(),
            allowed_custom_redirect_schemes=("cursor", "javascript"),
        )


def test_init_rejects_https_in_allowlist() -> None:
    with pytest.raises(ValueError, match="must not include 'https'"):
        DynamicClientRegistrationEndpoint(
            MockClientStore(),
            allowed_custom_redirect_schemes=("https",),
        )


def test_init_rejects_http_in_allowlist() -> None:
    with pytest.raises(ValueError, match="must not include 'http'"):
        DynamicClientRegistrationEndpoint(
            MockClientStore(),
            allowed_custom_redirect_schemes=("http",),
        )
