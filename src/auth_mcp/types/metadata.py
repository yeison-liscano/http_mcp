from pydantic import AnyHttpUrl, BaseModel, ConfigDict, field_validator


class ProtectedResourceMetadata(BaseModel):
    """RFC 9728 Protected Resource Metadata.

    Describes a protected resource (MCP server) and its relationship
    to authorization servers. URI fields are validated as HTTP/HTTPS URLs.
    """

    model_config = ConfigDict(frozen=True)

    resource: AnyHttpUrl
    authorization_servers: tuple[AnyHttpUrl, ...]
    scopes_supported: tuple[str, ...] | None = None
    bearer_methods_supported: tuple[str, ...] | None = None
    resource_signing_alg_values_supported: tuple[str, ...] | None = None
    resource_documentation: AnyHttpUrl | None = None


class AuthorizationServerMetadata(BaseModel):
    """RFC 8414 Authorization Server Metadata.

    Describes an OAuth 2.1 authorization server's endpoints and capabilities.
    URI fields are validated as HTTP/HTTPS URLs. The issuer must use HTTPS.
    """

    model_config = ConfigDict(frozen=True)

    issuer: AnyHttpUrl
    authorization_endpoint: AnyHttpUrl
    token_endpoint: AnyHttpUrl
    registration_endpoint: AnyHttpUrl | None = None
    scopes_supported: tuple[str, ...] | None = None
    response_types_supported: tuple[str, ...] = ("code",)
    grant_types_supported: tuple[str, ...] = ("authorization_code", "refresh_token")
    code_challenge_methods_supported: tuple[str, ...] = ("S256",)
    token_endpoint_auth_methods_supported: tuple[str, ...] = ("none",)
    revocation_endpoint: AnyHttpUrl | None = None

    @field_validator("issuer")
    @classmethod
    def _issuer_must_be_https(cls, v: AnyHttpUrl) -> AnyHttpUrl:
        if str(v).startswith("http://"):
            msg = "Issuer must use HTTPS"
            raise ValueError(msg)
        return v
