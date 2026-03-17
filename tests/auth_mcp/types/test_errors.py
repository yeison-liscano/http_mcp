import pytest
from pydantic import ValidationError

from auth_mcp.types.errors import OAuthErrorResponse, WWWAuthenticateChallenge


def test_oauth_error_response() -> None:
    error = OAuthErrorResponse(
        error="invalid_grant",
        error_description="The authorization code has expired",
    )
    assert error.error == "invalid_grant"
    assert error.error_description == "The authorization code has expired"
    assert error.error_uri is None


def test_oauth_error_response_minimal() -> None:
    error = OAuthErrorResponse(error="invalid_client")
    assert error.error_description is None
    assert error.error_uri is None


def test_oauth_error_response_serialization() -> None:
    error = OAuthErrorResponse(
        error="invalid_grant",
        error_description="expired",
    )
    data = error.model_dump(exclude_none=True)
    assert data == {"error": "invalid_grant", "error_description": "expired"}
    assert "error_uri" not in data


def test_www_authenticate_challenge_bearer_only() -> None:
    challenge = WWWAuthenticateChallenge()
    assert challenge.to_header_value() == "Bearer"


def test_www_authenticate_challenge_with_realm() -> None:
    challenge = WWWAuthenticateChallenge(realm="mcp-server")
    assert challenge.to_header_value() == 'Bearer realm="mcp-server"'


def test_www_authenticate_challenge_with_resource_metadata() -> None:
    challenge = WWWAuthenticateChallenge(
        resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource",
    )
    header = challenge.to_header_value()
    assert "resource_metadata=" in header
    assert "https://mcp.example.com/.well-known/oauth-protected-resource" in header


def test_www_authenticate_challenge_full() -> None:
    challenge = WWWAuthenticateChallenge(
        realm="mcp-server",
        resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource",
        scope="read write",
        error="insufficient_scope",
        error_description="The token does not have required scopes",
    )
    header = challenge.to_header_value()
    assert header.startswith("Bearer ")
    assert 'realm="mcp-server"' in header
    assert 'scope="read write"' in header
    assert 'error="insufficient_scope"' in header
    assert 'error_description="The token does not have required scopes"' in header


def test_www_authenticate_challenge_with_error_only() -> None:
    challenge = WWWAuthenticateChallenge(error="invalid_token")
    assert challenge.to_header_value() == 'Bearer error="invalid_token"'


def test_www_authenticate_sanitizes_double_quotes() -> None:
    challenge = WWWAuthenticateChallenge(realm='my"realm')
    header = challenge.to_header_value()
    assert '"' not in header.split('realm="')[1].split('"')[0] or '\\"' in header


def test_www_authenticate_sanitizes_backslash() -> None:
    challenge = WWWAuthenticateChallenge(realm="my\\realm")
    header = challenge.to_header_value()
    assert 'realm="my\\\\realm"' in header


def test_www_authenticate_sanitizes_crlf() -> None:
    challenge = WWWAuthenticateChallenge(error_description="line1\r\nline2")
    header = challenge.to_header_value()
    assert "\r" not in header
    assert "\n" not in header


def test_www_authenticate_sanitizes_injection_attempt() -> None:
    challenge = WWWAuthenticateChallenge(
        error_description='foo", evil="injected',
    )
    header = challenge.to_header_value()
    # The injected quote should be escaped, preventing a new parameter
    assert 'error_description="foo\\"' in header


def test_oauth_error_response_is_frozen() -> None:
    error = OAuthErrorResponse(error="invalid_grant")
    with pytest.raises(ValidationError):
        error.error = "other"


def test_www_authenticate_challenge_is_frozen() -> None:
    challenge = WWWAuthenticateChallenge()
    with pytest.raises(ValidationError):
        challenge.scheme = "Basic"
