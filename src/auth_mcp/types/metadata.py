from enum import Enum
from typing import Annotated, assert_never
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationInfo,
    field_validator,
)

_ISSUER_SYNTAX = TypeAdapter(AnyHttpUrl)
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class AuthorizationTransportPolicy(Enum):
    """Validation context for authorization metadata; never serialized as metadata."""

    HTTPS_ONLY = "https_only"
    ALLOW_LOOPBACK_HTTP = "allow_loopback_http"


def _loopback_http_is_allowed(value: str, info: ValidationInfo) -> bool:
    policy = (
        info.context
        if isinstance(info.context, AuthorizationTransportPolicy)
        else AuthorizationTransportPolicy.HTTPS_ONLY
    )
    match policy:
        case AuthorizationTransportPolicy.HTTPS_ONLY:
            return False
        case AuthorizationTransportPolicy.ALLOW_LOOPBACK_HTTP:
            # Inspect the original spelling: URL normalization can turn 127.1 or
            # an integer host into 127.0.0.1. Only explicit loopback hosts qualify.
            if (
                not value.lower().startswith("http://")
                or any(char.isspace() or char < "\x20" or char == "\x7f" for char in value)
                or "\\" in value
            ):
                return False
            parsed = urlsplit(value)
            return (
                parsed.hostname in _LOOPBACK_HOSTS
                and parsed.username is None
                and parsed.password is None
            )
        case _ as unreachable:
            assert_never(unreachable)


def _validate_issuer(value: str, info: ValidationInfo) -> str:
    """Validate issuer syntax without replacing the identifier with a normalized URL."""
    parsed = _ISSUER_SYNTAX.validate_python(value)
    if parsed.scheme != "https" and not _loopback_http_is_allowed(value, info):
        msg = "Issuer must use HTTPS (HTTP loopback requires explicit development opt-in)"
        raise ValueError(msg)
    if (
        not value.lower().startswith(f"{parsed.scheme}://")
        or any(char.isspace() or char < "\x20" or char == "\x7f" for char in value)
        or "\\" in value
        or parsed.query is not None
        or parsed.fragment is not None
        or parsed.username is not None
        or parsed.password is not None
    ):
        msg = "Issuer must be an absolute URL without credentials, query or fragment"
        raise ValueError(msg)
    return value


type IssuerUrl = Annotated[str, AfterValidator(_validate_issuer)]


class ProtectedResourceMetadata(BaseModel):
    """RFC 9728 Protected Resource Metadata.

    Describes a protected resource (MCP server) and its relationship
    to authorization servers. Issuer strings use the same validation-context
    transport policy as ``AuthorizationServerMetadata``; HTTPS is the default.
    """

    model_config = ConfigDict(frozen=True)

    resource: AnyHttpUrl
    authorization_servers: tuple[IssuerUrl, ...] = Field(min_length=1)
    scopes_supported: tuple[str, ...] | None = None
    bearer_methods_supported: tuple[str, ...] | None = None
    resource_signing_alg_values_supported: tuple[str, ...] | None = None
    resource_documentation: AnyHttpUrl | None = None


class AuthorizationServerMetadata(BaseModel):
    """RFC 8414 Authorization Server Metadata.

    Describes an OAuth 2.1 authorization server's endpoints and capabilities.
    HTTPS is required by default. Pass ``AuthorizationTransportPolicy.ALLOW_LOOPBACK_HTTP``
    as the validation context to allow explicit HTTP loopback URLs for development.
    Issuer spelling is preserved exactly under either policy.
    """

    model_config = ConfigDict(frozen=True)

    issuer: IssuerUrl
    authorization_endpoint: AnyHttpUrl
    token_endpoint: AnyHttpUrl
    registration_endpoint: AnyHttpUrl | None = None
    scopes_supported: tuple[str, ...] | None = None
    response_types_supported: tuple[str, ...] = ("code",)
    grant_types_supported: tuple[str, ...] = ("authorization_code", "refresh_token")
    code_challenge_methods_supported: tuple[str, ...] = ("S256",)
    token_endpoint_auth_methods_supported: tuple[str, ...] = ("none",)
    revocation_endpoint: AnyHttpUrl | None = None
    authorization_response_iss_parameter_supported: bool | None = None
    client_id_metadata_document_supported: bool | None = None

    @field_validator(
        "authorization_endpoint",
        "token_endpoint",
        "registration_endpoint",
        "revocation_endpoint",
        mode="before",
    )
    @classmethod
    def _validate_endpoint_transport(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> AnyHttpUrl | None:
        if value is None:
            return None
        parsed = _ISSUER_SYNTAX.validate_python(value)
        original = value if isinstance(value, str) else str(parsed)
        if parsed.scheme != "https" and not _loopback_http_is_allowed(original, info):
            msg = "Authorization server endpoints must use HTTPS (HTTP loopback requires opt-in)"
            raise ValueError(msg)
        return parsed
