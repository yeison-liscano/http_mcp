import json
from http import HTTPStatus

from starlette.testclient import TestClient

from auth_mcp.authorization_server.client_store import ClientStore
from auth_mcp.authorization_server.registration_endpoint import (
    DynamicClientRegistrationEndpoint,
)
from auth_mcp.exceptions import RegistrationError
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


class FailingClientStore(ClientStore):
    async def register_client(
        self,
        request: ClientRegistrationRequest,  # noqa: ARG002
    ) -> ClientRegistrationResponse:
        raise RegistrationError("Policy violation")  # noqa: TRY003


class CrashingClientStore(ClientStore):
    async def register_client(
        self,
        request: ClientRegistrationRequest,  # noqa: ARG002
    ) -> ClientRegistrationResponse:
        msg = "database connection lost"
        raise RuntimeError(msg)


def _create_client(store: ClientStore | None = None) -> TestClient:
    endpoint = DynamicClientRegistrationEndpoint(store or MockClientStore())
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
    client = _create_client(FailingClientStore())
    response = client.post("/", json=_valid_body())
    assert response.status_code == HTTPStatus.BAD_REQUEST
    data = response.json()
    assert data["error"] == "invalid_client_metadata"
    assert "Policy violation" in data["error_description"]


def test_oversized_body_returns_400() -> None:
    client = _create_client()
    large_body = json.dumps({"redirect_uris": ["https://example.com/callback"], "x": "a" * 70000})
    response = client.post(
        "/",
        content=large_body.encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    data = response.json()
    assert data["error"] == "invalid_client_metadata"


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
