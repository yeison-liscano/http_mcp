import pytest
from pydantic import ValidationError

from auth_mcp.types import AuthorizationTransportPolicy
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


def test_protected_resource_metadata_rejects_empty_authorization_servers() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        ProtectedResourceMetadata(resource="https://mcp.example.com", authorization_servers=())


@pytest.mark.parametrize(
    "issuer",
    [
        "https://auth.example.com",
        "https://auth.example.com/",
        "https://AUTH.example.com:443/%7Eissuer",
        "https://auth.example.com/a/../issuer",
    ],
)
def test_authorization_metadata_preserves_exact_issuer_identity(issuer: str) -> None:
    resource = ProtectedResourceMetadata(
        resource="https://mcp.example.com",
        authorization_servers=(issuer,),
    )
    server = AuthorizationServerMetadata(
        issuer=issuer,
        authorization_endpoint=_AS_AUTHORIZE,
        token_endpoint=_AS_TOKEN,
    )
    assert resource.model_dump(mode="json")["authorization_servers"] == [issuer]
    assert server.model_dump(mode="json")["issuer"] == issuer
    assert resource.authorization_servers == (issuer,)
    assert server.issuer == issuer
    assert (
        AuthorizationServerMetadata.model_validate_json(server.model_dump_json()).issuer == issuer
    )


@pytest.mark.parametrize(
    "issuer",
    [
        "http://auth.example.com",
        "not-a-url",
        "https:auth.example.com",
        " https://auth.example.com",
        "https://auth.example.com\n",
        "https://auth.example.com?query",
        "https://auth.example.com#fragment",
        "https://user:password@auth.example.com",
        "https://auth.example.com\\issuer",
    ],
)
def test_issuer_validation_rejects_invalid_identity_syntax(issuer: str) -> None:
    with pytest.raises(ValidationError):
        ProtectedResourceMetadata(
            resource="https://mcp.example.com",
            authorization_servers=(issuer,),
        )
    with pytest.raises(ValidationError):
        AuthorizationServerMetadata(
            issuer=issuer,
            authorization_endpoint=_AS_AUTHORIZE,
            token_endpoint=_AS_TOKEN,
        )


@pytest.mark.parametrize("supported", [True, False])
def test_authorization_server_metadata_retains_capability_flags(*, supported: bool) -> None:
    server = AuthorizationServerMetadata(
        issuer=_AS_ISSUER,
        authorization_endpoint=_AS_AUTHORIZE,
        token_endpoint=_AS_TOKEN,
        authorization_response_iss_parameter_supported=supported,
        client_id_metadata_document_supported=supported,
    )
    data = server.model_dump(mode="json", exclude_none=True)
    assert data["authorization_response_iss_parameter_supported"] is supported
    assert data["client_id_metadata_document_supported"] is supported


@pytest.mark.parametrize(
    "endpoint",
    ["authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"],
)
def test_authorization_server_metadata_rejects_http_endpoints(endpoint: str) -> None:
    data = {
        "issuer": _AS_ISSUER,
        "authorization_endpoint": _AS_AUTHORIZE,
        "token_endpoint": _AS_TOKEN,
        endpoint: "http://auth.example.com/endpoint",
    }
    with pytest.raises(ValidationError, match="endpoints must use HTTPS"):
        AuthorizationServerMetadata.model_validate(data)


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
    assert str(metadata.issuer) == _AS_ISSUER
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


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]", "LOCALHOST"])
def test_loopback_http_requires_opt_in_and_preserves_exact_issuer(host: str) -> None:
    issuer = f"http://{host}:8000/%7Eissuer"
    server_data = {
        "issuer": issuer,
        "authorization_endpoint": f"http://{host}:8000/authorize",
        "token_endpoint": f"http://{host}:8000/token",
        "registration_endpoint": f"http://{host}:8000/register",
        "revocation_endpoint": f"http://{host}:8000/revoke",
    }
    resource_data = {"resource": "http://localhost:8001/mcp", "authorization_servers": (issuer,)}
    for context in (None, AuthorizationTransportPolicy.HTTPS_ONLY):
        with pytest.raises(ValidationError, match="Issuer must use HTTPS"):
            AuthorizationServerMetadata.model_validate(server_data, context=context)
        with pytest.raises(ValidationError, match="Issuer must use HTTPS"):
            ProtectedResourceMetadata.model_validate(resource_data, context=context)

    policy = AuthorizationTransportPolicy.ALLOW_LOOPBACK_HTTP
    server = AuthorizationServerMetadata.model_validate(server_data, context=policy)
    resource = ProtectedResourceMetadata.model_validate(resource_data, context=policy)
    assert server.issuer == issuer
    assert resource.authorization_servers == (issuer,)
    assert server.model_dump(mode="json", exclude_none=True) == {
        **{
            name: value if name == "issuer" else value.replace(host, host.lower())
            for name, value in server_data.items()
        },
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }
    assert (
        AuthorizationServerMetadata.model_validate_json(
            server.model_dump_json(),
            context=policy,
        ).issuer
        == issuer
    )
    with pytest.raises(ValidationError):
        AuthorizationServerMetadata.model_validate_json(server.model_dump_json())


@pytest.mark.parametrize(
    "url",
    [
        "http://auth.example.com",
        "http://localhost.evil.example",
        "http://localhost.",
        "http://foo.localhost",
        "http://0.0.0.0",
        "http://127.0.0.2",
        "http://127.1",
        "http://2130706433",
        "http://0x7f000001",
        "http://[::ffff:127.0.0.1]",
        "http://user@localhost",
        "http://localhost@evil.example",
        "http://evil.example\\@localhost",
        "http://localhost\n",
        "http://localhost\t/authorize",
        "http:localhost",
    ],
)
def test_loopback_opt_in_rejects_remote_and_obfuscated_http_urls(url: str) -> None:
    policy = AuthorizationTransportPolicy.ALLOW_LOOPBACK_HTTP
    with pytest.raises(ValidationError):
        ProtectedResourceMetadata.model_validate(
            {"resource": "https://mcp.example.com", "authorization_servers": (url,)},
            context=policy,
        )
    with pytest.raises(ValidationError):
        AuthorizationServerMetadata.model_validate(
            {"issuer": url, "authorization_endpoint": _AS_AUTHORIZE, "token_endpoint": _AS_TOKEN},
            context=policy,
        )
    with pytest.raises(ValidationError):
        AuthorizationServerMetadata.model_validate(
            {"issuer": _AS_ISSUER, "authorization_endpoint": url, "token_endpoint": _AS_TOKEN},
            context=policy,
        )


@pytest.mark.parametrize(
    "endpoint",
    ["authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"],
)
def test_each_endpoint_requires_explicit_loopback_policy(endpoint: str) -> None:
    url = "http://localhost:8000/endpoint?audience=user@example.com"
    data = {
        "issuer": _AS_ISSUER,
        "authorization_endpoint": _AS_AUTHORIZE,
        "token_endpoint": _AS_TOKEN,
        endpoint: url,
    }
    with pytest.raises(ValidationError, match="endpoints must use HTTPS"):
        AuthorizationServerMetadata.model_validate(data)
    metadata = AuthorizationServerMetadata.model_validate(
        data,
        context=AuthorizationTransportPolicy.ALLOW_LOOPBACK_HTTP,
    )
    assert metadata.model_dump(mode="json")[endpoint] == url
