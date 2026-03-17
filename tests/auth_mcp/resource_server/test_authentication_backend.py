import pytest
from starlette.authentication import UnauthenticatedUser
from starlette.requests import HTTPConnection

from auth_mcp.resource_server.authentication_backend import OAuthAuthenticationBackend
from auth_mcp.resource_server.token_validator import TokenInfo, TokenValidator

_VALID_ACCESS_TOKEN = "valid_access_token"  # noqa: S105


class MockTokenValidator(TokenValidator):
    async def validate_token(
        self,
        token: str,
        resource: str | None = None,
    ) -> TokenInfo | None:
        if token == _VALID_ACCESS_TOKEN:
            return TokenInfo(
                subject="user@example.com",
                scopes=("read", "write"),
                client_id="test_client",
                audience=resource,
            )
        return None


def _make_connection(headers: dict[str, str] | None = None) -> HTTPConnection:
    """Create a minimal HTTPConnection with given headers for testing."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
    }
    return HTTPConnection(scope)


@pytest.mark.asyncio
async def test_valid_bearer_token() -> None:
    backend = OAuthAuthenticationBackend(
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        require_authentication=False,
    )
    conn = _make_connection({"Authorization": f"Bearer {_VALID_ACCESS_TOKEN}"})
    credentials, user = await backend.authenticate(conn)
    assert user.display_name == "user@example.com"
    assert "read" in credentials.scopes
    assert "write" in credentials.scopes


@pytest.mark.asyncio
async def test_invalid_bearer_token() -> None:
    backend = OAuthAuthenticationBackend(
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        require_authentication=False,
    )
    conn = _make_connection({"Authorization": "Bearer bad_token"})
    credentials, user = await backend.authenticate(conn)
    assert isinstance(user, UnauthenticatedUser)
    assert len(credentials.scopes) == 0


@pytest.mark.asyncio
async def test_missing_authorization_header() -> None:
    backend = OAuthAuthenticationBackend(
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        require_authentication=False,
    )
    conn = _make_connection()
    credentials, user = await backend.authenticate(conn)
    assert isinstance(user, UnauthenticatedUser)
    assert len(credentials.scopes) == 0


@pytest.mark.asyncio
async def test_non_bearer_scheme() -> None:
    backend = OAuthAuthenticationBackend(
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        require_authentication=False,
    )
    conn = _make_connection({"Authorization": "Basic dXNlcjpwYXNz"})
    _, user = await backend.authenticate(conn)
    assert isinstance(user, UnauthenticatedUser)


@pytest.mark.asyncio
async def test_malformed_authorization_header() -> None:
    backend = OAuthAuthenticationBackend(
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        require_authentication=False,
    )
    conn = _make_connection({"Authorization": "InvalidHeader"})
    _, user = await backend.authenticate(conn)
    assert isinstance(user, UnauthenticatedUser)


@pytest.mark.asyncio
async def test_bearer_case_insensitive() -> None:
    backend = OAuthAuthenticationBackend(
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        require_authentication=False,
    )
    conn = _make_connection({"Authorization": f"BEARER {_VALID_ACCESS_TOKEN}"})
    credentials, user = await backend.authenticate(conn)
    assert user.display_name == "user@example.com"
    assert "read" in credentials.scopes


@pytest.mark.asyncio
async def test_require_authentication_default_is_true() -> None:
    backend = OAuthAuthenticationBackend(
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
    )
    conn = _make_connection()
    with pytest.raises(Exception, match="Authentication required"):
        await backend.authenticate(conn)


@pytest.mark.asyncio
async def test_non_bearer_scheme_raises_when_auth_required() -> None:
    backend = OAuthAuthenticationBackend(
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
    )
    conn = _make_connection({"Authorization": "Basic dXNlcjpwYXNz"})
    with pytest.raises(Exception, match="Invalid authorization scheme"):
        await backend.authenticate(conn)


@pytest.mark.asyncio
async def test_malformed_token_raises_when_auth_required() -> None:
    backend = OAuthAuthenticationBackend(
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
    )
    conn = _make_connection({"Authorization": "Bearer tok\x00en"})
    with pytest.raises(Exception, match="Malformed bearer token"):
        await backend.authenticate(conn)


@pytest.mark.asyncio
async def test_rejects_oversized_token() -> None:
    backend = OAuthAuthenticationBackend(
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        require_authentication=False,
    )
    oversized = "A" * 3000
    conn = _make_connection({"Authorization": f"Bearer {oversized}"})
    _, user = await backend.authenticate(conn)
    assert isinstance(user, UnauthenticatedUser)


@pytest.mark.asyncio
async def test_rejects_token_with_special_chars() -> None:
    backend = OAuthAuthenticationBackend(
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        require_authentication=False,
    )
    conn = _make_connection({"Authorization": "Bearer tok\x00en"})
    _, user = await backend.authenticate(conn)
    assert isinstance(user, UnauthenticatedUser)


@pytest.mark.asyncio
async def test_rejects_token_with_spaces() -> None:
    backend = OAuthAuthenticationBackend(
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        require_authentication=False,
    )
    conn = _make_connection({"Authorization": "Bearer tok en"})
    _, user = await backend.authenticate(conn)
    assert isinstance(user, UnauthenticatedUser)
