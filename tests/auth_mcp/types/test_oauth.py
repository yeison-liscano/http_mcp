import pytest
from pydantic import TypeAdapter, ValidationError

from auth_mcp.types.oauth import (
    AuthorizationCodeTokenRequest,
    AuthorizationRequest,
    RefreshTokenRequest,
    TokenRequest,
    TokenResponse,
)

_EXPECTED_EXPIRES_IN = 3600
_TOKEN_REQUEST: TypeAdapter[AuthorizationCodeTokenRequest | RefreshTokenRequest] = TypeAdapter(
    TokenRequest,
)


def test_token_request_authorization_code() -> None:
    request = AuthorizationCodeTokenRequest(
        grant_type="authorization_code",
        code="abc123",
        redirect_uri="https://client.example.com/callback",
        code_verifier="verifier_value",
        client_id="client_123",
        resource="https://mcp.example.com",
    )
    assert request.grant_type == "authorization_code"
    assert request.code == "abc123"
    assert request.resource == "https://mcp.example.com"


def test_token_request_refresh_token() -> None:
    request = RefreshTokenRequest(
        grant_type="refresh_token",
        refresh_token="refresh_abc",  # noqa: S106
        client_id="client_123",
    )
    assert request.grant_type == "refresh_token"
    assert request.refresh_token == "refresh_abc"  # noqa: S105


def test_token_request_rejects_invalid_grant_type() -> None:
    with pytest.raises(ValidationError):
        _TOKEN_REQUEST.validate_python({"grant_type": "client_credentials"})


def test_token_request_selects_the_variant_from_the_grant_type() -> None:
    code_grant = _TOKEN_REQUEST.validate_python(
        {"grant_type": "authorization_code", "code": "abc", "code_verifier": "xyz"},
    )
    refresh_grant = _TOKEN_REQUEST.validate_python(
        {"grant_type": "refresh_token", "refresh_token": "abc"},
    )
    assert isinstance(code_grant, AuthorizationCodeTokenRequest)
    assert isinstance(refresh_grant, RefreshTokenRequest)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"grant_type": "authorization_code"}, id="code-grant-without-code"),
        pytest.param(
            {"grant_type": "authorization_code", "code": "abc"},
            id="code-grant-without-pkce-verifier",
        ),
        pytest.param(
            {"grant_type": "authorization_code", "refresh_token": "abc"},
            id="code-grant-with-only-a-refresh-token",
        ),
        pytest.param({"grant_type": "refresh_token"}, id="refresh-grant-without-token"),
        pytest.param(
            {"grant_type": "refresh_token", "code": "abc", "code_verifier": "xyz"},
            id="refresh-grant-with-only-a-code",
        ),
    ],
)
def test_token_request_rejects_fields_of_the_wrong_grant(fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        _TOKEN_REQUEST.validate_python(fields)


def test_token_response() -> None:
    response = TokenResponse(
        access_token="access_abc",  # noqa: S106
        expires_in=_EXPECTED_EXPIRES_IN,
        refresh_token="refresh_abc",  # noqa: S106
        scope="read write",
    )
    assert response.access_token == "access_abc"  # noqa: S105
    assert response.token_type == "Bearer"  # noqa: S105
    assert response.expires_in == _EXPECTED_EXPIRES_IN
    assert response.refresh_token == "refresh_abc"  # noqa: S105
    assert response.scope == "read write"


def test_token_response_defaults() -> None:
    response = TokenResponse(access_token="tok", expires_in=60)  # noqa: S106
    assert response.token_type == "Bearer"  # noqa: S105
    assert response.refresh_token is None
    assert response.scope is None


def test_authorization_request() -> None:
    request = AuthorizationRequest(
        client_id="client_123",
        redirect_uri="https://client.example.com/callback",
        code_challenge="challenge_value",
        scope="read write",
        state="random_state",
        resource="https://mcp.example.com",
    )
    assert request.response_type == "code"
    assert request.client_id == "client_123"
    assert request.code_challenge_method == "S256"
    assert request.resource == "https://mcp.example.com"


def test_authorization_request_defaults() -> None:
    request = AuthorizationRequest(
        client_id="client_123",
        redirect_uri="https://client.example.com/callback",
        code_challenge="challenge_value",
    )
    assert request.response_type == "code"
    assert request.code_challenge_method == "S256"
    assert request.scope is None
    assert request.state is None
    assert request.resource is None


def test_authorization_request_rejects_plain_code_challenge_method() -> None:
    with pytest.raises(ValidationError):
        AuthorizationRequest(
            client_id="client_123",
            redirect_uri="https://client.example.com/callback",
            code_challenge="challenge_value",
            code_challenge_method="plain",
        )


def test_token_response_is_frozen() -> None:
    response = TokenResponse(access_token="tok", expires_in=60)  # noqa: S106
    with pytest.raises(ValidationError):
        response.access_token = "other"  # noqa: S105
