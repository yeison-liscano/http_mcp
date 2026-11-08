from http import HTTPStatus

import pytest
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
    response = client.get("/", headers={"Authorization": "Bearer expired-token"})
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert "www-authenticate" in response.headers
    www_auth = response.headers["www-authenticate"]
    assert "Bearer" in www_auth
    assert "resource_metadata=" in www_auth
    assert 'error="invalid_token"' in www_auth


def _app_returning(status: HTTPStatus, headers: dict[str, str] | None = None) -> TestClient:
    async def endpoint(_request: Request) -> Response:
        return Response(status_code=status, headers=headers)

    return TestClient(
        Starlette(
            routes=[Route("/", endpoint)],
            middleware=[
                Middleware(
                    AuthErrorMiddleware,
                    resource_metadata_url="https://mcp.example.com/.well-known/oauth-protected-resource",
                ),
            ],
        ),
    )


@pytest.mark.parametrize("authorization", [None, "Basic dXNlcjpwYXNz", "Digest x"])
def test_401_without_bearer_credentials_carries_no_error(authorization: str | None) -> None:
    """RFC 6750 section 3.1: no token was presented, so none can be called invalid."""
    sent = {"Authorization": authorization} if authorization is not None else None

    response = _app_returning(HTTPStatus.UNAUTHORIZED).get("/", headers=sent)

    assert response.headers["www-authenticate"] == (
        'Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource"'
    )


def test_403_keeps_the_scope_the_app_named_in_one_challenge() -> None:
    """The scope drives step-up authorization; the app's challenge is replaced, not doubled."""
    client = _app_returning(
        HTTPStatus.FORBIDDEN,
        {"WWW-Authenticate": 'Bearer error="insufficient_scope", scope="admin billing:write"'},
    )

    response = client.get("/", headers={"Authorization": "Bearer token"})

    metadata = "https://mcp.example.com/.well-known/oauth-protected-resource"
    expected = (
        f'Bearer resource_metadata="{metadata}", '
        'scope="admin billing:write", error="insufficient_scope"'
    )
    assert response.headers.get_list("www-authenticate") == [expected]


def test_403_without_a_scope_from_the_app_names_none() -> None:
    response = _app_returning(HTTPStatus.FORBIDDEN).get("/")

    assert "scope=" not in response.headers["www-authenticate"]
    assert 'error="insufficient_scope"' in response.headers["www-authenticate"]


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
