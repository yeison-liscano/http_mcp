from http import HTTPStatus

from starlette.testclient import TestClient

from auth_mcp.resource_server.metadata_endpoint import ProtectedResourceMetadataEndpoint
from auth_mcp.types.metadata import ProtectedResourceMetadata


def _create_metadata() -> ProtectedResourceMetadata:
    return ProtectedResourceMetadata(
        resource="https://mcp.example.com",
        authorization_servers=("https://auth.example.com",),
        scopes_supported=("read", "write"),
    )


def _create_client() -> TestClient:
    metadata = _create_metadata()
    endpoint = ProtectedResourceMetadataEndpoint(metadata)
    return TestClient(endpoint)


def test_get_returns_metadata_json() -> None:
    client = _create_client()
    response = client.get("/")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["resource"] == "https://mcp.example.com/"
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
    metadata = ProtectedResourceMetadata(
        resource="https://mcp.example.com",
        authorization_servers=("https://auth.example.com",),
    )
    endpoint = ProtectedResourceMetadataEndpoint(metadata)
    client = TestClient(endpoint)
    response = client.get("/")
    data = response.json()
    assert "scopes_supported" not in data
    assert "bearer_methods_supported" not in data
    assert "resource_documentation" not in data
