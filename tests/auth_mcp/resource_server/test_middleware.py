from http import HTTPStatus

from starlette.applications import Starlette
from starlette.authentication import AuthenticationError
from starlette.middleware import Middleware
from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from auth_mcp.resource_server.middleware import (
    AuthErrorMiddleware,
    build_www_authenticate_header,
    on_auth_error,
)


def test_build_www_authenticate_header_basic() -> None:
    header = build_www_authenticate_header(
        resource_metadata_url="https://mcp.example.com/.well-known/oauth-protected-resource",
    )
    assert header.startswith("Bearer ")
    assert "resource_metadata=" in header


def test_build_www_authenticate_header_with_all_params() -> None:
    header = build_www_authenticate_header(
        resource_metadata_url="https://mcp.example.com/.well-known/oauth-protected-resource",
        realm="mcp",
        scope="read write",
        error="invalid_token",
        error_description="Token expired",
    )
    assert 'realm="mcp"' in header
    assert 'scope="read write"' in header
    assert 'error="invalid_token"' in header
    assert 'error_description="Token expired"' in header


def test_auth_error_middleware_adds_www_authenticate_on_401() -> None:
    async def return_401(_request: Request) -> Response:
        return Response(status_code=HTTPStatus.UNAUTHORIZED, content="Unauthorized")

    app = Starlette(
        routes=[Route("/", return_401)],
        middleware=[
            Middleware(
                AuthErrorMiddleware,
                resource_metadata_url="https://mcp.example.com/.well-known/oauth-protected-resource",
            ),
        ],
    )
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert "www-authenticate" in response.headers
    www_auth = response.headers["www-authenticate"]
    assert "Bearer" in www_auth
    assert "resource_metadata=" in www_auth
    assert 'error="invalid_token"' in www_auth


def test_auth_error_middleware_adds_www_authenticate_on_403() -> None:
    async def return_403(_request: Request) -> Response:
        return Response(status_code=HTTPStatus.FORBIDDEN, content="Forbidden")

    app = Starlette(
        routes=[Route("/", return_403)],
        middleware=[
            Middleware(
                AuthErrorMiddleware,
                resource_metadata_url="https://mcp.example.com/.well-known/oauth-protected-resource",
                realm="mcp",
            ),
        ],
    )
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert "www-authenticate" in response.headers
    www_auth = response.headers["www-authenticate"]
    assert 'realm="mcp"' in www_auth


def test_auth_error_middleware_adds_security_headers_on_200() -> None:
    async def return_ok(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    app = Starlette(
        routes=[Route("/", return_ok)],
        middleware=[
            Middleware(
                AuthErrorMiddleware,
                resource_metadata_url="https://mcp.example.com/.well-known/oauth-protected-resource",
            ),
        ],
    )
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == HTTPStatus.OK
    assert "www-authenticate" not in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "max-age=" in response.headers["strict-transport-security"]


def test_on_auth_error_returns_json_401() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
    }
    conn = HTTPConnection(scope)
    response = on_auth_error(conn, AuthenticationError("auth failed"))
    assert response.status_code == HTTPStatus.UNAUTHORIZED
