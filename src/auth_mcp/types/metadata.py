from typing import Annotated

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
)

_ISSUER_SYNTAX = TypeAdapter(AnyHttpUrl)


def _validate_issuer(value: str) -> str:
    """Validate issuer syntax without replacing the identifier with a normalized URL."""
    parsed = _ISSUER_SYNTAX.validate_python(value)
    if parsed.scheme != "https":
        msg = "Issuer must use HTTPS"
        raise ValueError(msg)
    if (
        not value.lower().startswith("https://")
        or any(char.isspace() or char < "\x20" or char == "\x7f" for char in value)
        or "\\" in value
        or parsed.query is not None
        or parsed.fragment is not None
        or parsed.username is not None
        or parsed.password is not None
    ):
        msg = "Issuer must be an absolute HTTPS URL without credentials, query or fragment"
        raise ValueError(msg)
    return value


type IssuerUrl = Annotated[str, AfterValidator(_validate_issuer)]


class ProtectedResourceMetadata(BaseModel):
    """RFC 9728 Protected Resource Metadata.

    Describes a protected resource (MCP server) and its relationship
    to authorization servers. URI fields are validated as HTTP/HTTPS URLs.
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
    The issuer is an exact, validated HTTPS string. Endpoints are HTTPS URLs.
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
    )
    @classmethod
    def _endpoint_must_be_https(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None and value.scheme != "https":
            msg = "Authorization server endpoints must use HTTPS"
            raise ValueError(msg)
        return value
