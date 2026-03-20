from http import HTTPStatus

from starlette.testclient import TestClient

from auth_mcp.authorization_server.metadata_endpoint import AuthorizationServerMetadataEndpoint
from auth_mcp.types.metadata import AuthorizationServerMetadata


def _create_metadata() -> AuthorizationServerMetadata:
    return AuthorizationServerMetadata(
        issuer="https://auth.example.com",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",  # noqa: S106
        registration_endpoint="https://auth.example.com/register",
        scopes_supported=("read", "write"),
    )


def _create_client() -> TestClient:
    metadata = _create_metadata()
    endpoint = AuthorizationServerMetadataEndpoint(metadata)
    return TestClient(endpoint)


def test_get_returns_metadata_json() -> None:
    client = _create_client()
    response = client.get("/")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["issuer"] == "https://auth.example.com/"
    assert data["authorization_endpoint"] == "https://auth.example.com/authorize"
    assert data["token_endpoint"] == "https://auth.example.com/token"  # noqa: S105
    assert data["scopes_supported"] == ["read", "write"]


def test_get_content_type_is_json() -> None:
    client = _create_client()
    response = client.get("/")
    assert "application/json" in response.headers["content-type"]


def test_get_security_headers() -> None:
    client = _create_client()
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "strict-transport-security" in response.headers
    assert "max-age=" in response.headers["strict-transport-security"]


def test_post_method_not_allowed() -> None:
    client = _create_client()
    response = client.post("/")
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert response.headers["allow"] == "GET"


def test_put_method_not_allowed() -> None:
    client = _create_client()
    response = client.put("/")
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_excludes_none_fields() -> None:
    metadata = AuthorizationServerMetadata(
        issuer="https://auth.example.com",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",  # noqa: S106
    )
    endpoint = AuthorizationServerMetadataEndpoint(metadata)
    client = TestClient(endpoint)
    response = client.get("/")
    data = response.json()
    assert "registration_endpoint" not in data
    assert "scopes_supported" not in data
    assert "revocation_endpoint" not in data


def test_registration_endpoint_included_when_set() -> None:
    client = _create_client()
    response = client.get("/")
    data = response.json()
    assert data["registration_endpoint"] == "https://auth.example.com/register"
