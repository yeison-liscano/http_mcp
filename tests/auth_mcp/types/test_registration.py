import pytest
from pydantic import ValidationError

from auth_mcp.types.registration import (
    ClientRegistrationRequest,
    ClientRegistrationResponse,
)

_EXPECTED_REDIRECT_URI_COUNT = 2
_EXPECTED_ISSUED_AT = 1700000000
_EXPECTED_SECRET_EXPIRES_AT = 1700003600


def test_client_registration_request_minimal() -> None:
    request = ClientRegistrationRequest(
        redirect_uris=("https://client.example.com/callback",),
    )
    assert request.redirect_uris == ("https://client.example.com/callback",)
    assert request.client_name is None
    assert request.grant_types == ("authorization_code",)
    assert request.response_types == ("code",)
    assert request.token_endpoint_auth_method == "none"  # noqa: S105


def test_client_registration_request_all_fields() -> None:
    request = ClientRegistrationRequest(
        redirect_uris=(
            "https://client.example.com/callback",
            "https://client.example.com/callback2",
        ),
        client_name="My MCP Client",
        grant_types=("authorization_code", "refresh_token"),
        response_types=("code",),
        token_endpoint_auth_method="client_secret_basic",  # noqa: S106
    )
    assert request.client_name == "My MCP Client"
    assert len(request.redirect_uris) == _EXPECTED_REDIRECT_URI_COUNT


def test_client_registration_request_allows_localhost_http() -> None:
    request = ClientRegistrationRequest(
        redirect_uris=("http://localhost:8080/callback",),
    )
    assert request.redirect_uris == ("http://localhost:8080/callback",)


def test_client_registration_request_allows_127_0_0_1_http() -> None:
    request = ClientRegistrationRequest(
        redirect_uris=("http://127.0.0.1:8080/callback",),
    )
    assert request.redirect_uris == ("http://127.0.0.1:8080/callback",)


def test_client_registration_request_rejects_http_non_localhost() -> None:
    with pytest.raises(ValidationError, match="HTTP redirect URIs are only allowed for localhost"):
        ClientRegistrationRequest(
            redirect_uris=("http://attacker.example.com/callback",),
        )


def test_client_registration_request_rejects_javascript_uri() -> None:
    with pytest.raises(ValidationError, match="must be an absolute URI"):
        ClientRegistrationRequest(
            redirect_uris=("javascript:alert(1)",),
        )


def test_client_registration_request_rejects_data_uri() -> None:
    with pytest.raises(ValidationError, match="must be an absolute URI"):
        ClientRegistrationRequest(
            redirect_uris=("data:text/html,<script>alert(1)</script>",),
        )


def test_client_registration_request_rejects_ftp_scheme() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        ClientRegistrationRequest(
            redirect_uris=("ftp://files.example.com/callback",),
        )


def test_client_registration_request_rejects_relative_uri() -> None:
    with pytest.raises(ValidationError, match="must be an absolute URI"):
        ClientRegistrationRequest(
            redirect_uris=("/callback",),
        )


def test_client_registration_response() -> None:
    response = ClientRegistrationResponse(
        client_id="client_abc",
        client_id_issued_at=_EXPECTED_ISSUED_AT,
        redirect_uris=("https://client.example.com/callback",),
        grant_types=("authorization_code",),
        response_types=("code",),
        token_endpoint_auth_method="none",  # noqa: S106
    )
    assert response.client_id == "client_abc"
    assert response.client_secret is None
    assert response.client_secret_expires_at is None
    assert response.client_id_issued_at == _EXPECTED_ISSUED_AT


def test_client_registration_response_with_secret() -> None:
    response = ClientRegistrationResponse(
        client_id="client_abc",
        client_secret="secret_xyz",  # noqa: S106
        client_secret_expires_at=_EXPECTED_SECRET_EXPIRES_AT,
        redirect_uris=("https://client.example.com/callback",),
        grant_types=("authorization_code",),
        response_types=("code",),
        token_endpoint_auth_method="client_secret_basic",  # noqa: S106
    )
    assert response.client_secret == "secret_xyz"  # noqa: S105
    assert response.client_secret_expires_at == _EXPECTED_SECRET_EXPIRES_AT


def test_client_registration_response_is_frozen() -> None:
    response = ClientRegistrationResponse(
        client_id="client_abc",
        redirect_uris=("https://client.example.com/callback",),
        grant_types=("authorization_code",),
        response_types=("code",),
        token_endpoint_auth_method="none",  # noqa: S106
    )
    with pytest.raises(ValidationError):
        response.client_id = "other"
