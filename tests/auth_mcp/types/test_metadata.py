import pytest
from pydantic import ValidationError

from auth_mcp.types.metadata import (
    AuthorizationServerMetadata,
    ProtectedResourceMetadata,
)

_AS_ISSUER = "https://auth.example.com"
_AS_AUTHORIZE = "https://auth.example.com/authorize"
_AS_TOKEN = "https://auth.example.com/token"  # noqa: S105
_EXPECTED_MULTI_SERVER_COUNT = 2


def test_protected_resource_metadata_required_fields() -> None:
    metadata = ProtectedResourceMetadata(
        resource="https://mcp.example.com",
        authorization_servers=("https://auth.example.com",),
    )
    assert str(metadata.resource) == "https://mcp.example.com/"
    assert metadata.scopes_supported is None
    assert metadata.bearer_methods_supported is None


def test_protected_resource_metadata_all_fields() -> None:
    metadata = ProtectedResourceMetadata(
        resource="https://mcp.example.com",
        authorization_servers=("https://auth.example.com",),
        scopes_supported=("read", "write"),
        bearer_methods_supported=("header",),
        resource_documentation="https://docs.example.com",
    )
    assert metadata.scopes_supported == ("read", "write")
    assert metadata.bearer_methods_supported == ("header",)
    assert str(metadata.resource_documentation) == "https://docs.example.com/"


def test_protected_resource_metadata_serialization() -> None:
    metadata = ProtectedResourceMetadata(
        resource="https://mcp.example.com",
        authorization_servers=("https://auth.example.com",),
        scopes_supported=("read",),
    )
    data = metadata.model_dump(mode="json", exclude_none=True)
    assert data["resource"] == "https://mcp.example.com/"
    assert data["scopes_supported"] == ["read"]


def test_protected_resource_metadata_multiple_authorization_servers() -> None:
    metadata = ProtectedResourceMetadata(
        resource="https://mcp.example.com",
        authorization_servers=(
            "https://auth1.example.com",
            "https://auth2.example.com",
        ),
    )
    assert len(metadata.authorization_servers) == _EXPECTED_MULTI_SERVER_COUNT


def test_protected_resource_metadata_rejects_invalid_uri() -> None:
    with pytest.raises(ValidationError):
        ProtectedResourceMetadata(
            resource="not-a-url",
            authorization_servers=("https://auth.example.com",),
        )


def test_protected_resource_metadata_rejects_javascript_uri() -> None:
    with pytest.raises(ValidationError):
        ProtectedResourceMetadata(
            resource="javascript:alert(1)",
            authorization_servers=("https://auth.example.com",),
        )


def test_protected_resource_metadata_is_frozen() -> None:
    metadata = ProtectedResourceMetadata(
        resource="https://mcp.example.com",
        authorization_servers=("https://auth.example.com",),
    )
    with pytest.raises(ValidationError):
        metadata.resource = "https://other.example.com"


def test_authorization_server_metadata_required_fields() -> None:
    metadata = AuthorizationServerMetadata(
        issuer=_AS_ISSUER,
        authorization_endpoint=_AS_AUTHORIZE,
        token_endpoint=_AS_TOKEN,
    )
    assert str(metadata.issuer) == f"{_AS_ISSUER}/"
    assert metadata.registration_endpoint is None


def test_authorization_server_metadata_defaults() -> None:
    metadata = AuthorizationServerMetadata(
        issuer=_AS_ISSUER,
        authorization_endpoint=_AS_AUTHORIZE,
        token_endpoint=_AS_TOKEN,
    )
    assert metadata.response_types_supported == ("code",)
    assert metadata.grant_types_supported == ("authorization_code", "refresh_token")
    assert metadata.code_challenge_methods_supported == ("S256",)
    assert metadata.token_endpoint_auth_methods_supported == ("none",)


def test_authorization_server_metadata_all_fields() -> None:
    metadata = AuthorizationServerMetadata(
        issuer=_AS_ISSUER,
        authorization_endpoint=_AS_AUTHORIZE,
        token_endpoint=_AS_TOKEN,
        registration_endpoint="https://auth.example.com/register",
        scopes_supported=("read", "write", "admin"),
        response_types_supported=("code",),
        grant_types_supported=("authorization_code",),
        code_challenge_methods_supported=("S256",),
        token_endpoint_auth_methods_supported=("none", "client_secret_basic"),
        revocation_endpoint="https://auth.example.com/revoke",
    )
    assert str(metadata.registration_endpoint) == "https://auth.example.com/register"
    assert metadata.scopes_supported == ("read", "write", "admin")


def test_authorization_server_metadata_serialization_excludes_none() -> None:
    metadata = AuthorizationServerMetadata(
        issuer=_AS_ISSUER,
        authorization_endpoint=_AS_AUTHORIZE,
        token_endpoint=_AS_TOKEN,
    )
    data = metadata.model_dump(exclude_none=True)
    assert "registration_endpoint" not in data
    assert "scopes_supported" not in data
    assert "revocation_endpoint" not in data


def test_authorization_server_metadata_issuer_must_be_https() -> None:
    with pytest.raises(ValidationError, match="Issuer must use HTTPS"):
        AuthorizationServerMetadata(
            issuer="http://auth.example.com",
            authorization_endpoint=_AS_AUTHORIZE,
            token_endpoint=_AS_TOKEN,
        )


def test_authorization_server_metadata_rejects_invalid_endpoint() -> None:
    with pytest.raises(ValidationError):
        AuthorizationServerMetadata(
            issuer=_AS_ISSUER,
            authorization_endpoint="not-a-url",
            token_endpoint=_AS_TOKEN,
        )


def test_authorization_server_metadata_is_frozen() -> None:
    metadata = AuthorizationServerMetadata(
        issuer=_AS_ISSUER,
        authorization_endpoint=_AS_AUTHORIZE,
        token_endpoint=_AS_TOKEN,
    )
    with pytest.raises(ValidationError):
        metadata.issuer = "https://other.example.com"
