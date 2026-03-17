from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator


class ClientRegistrationRequest(BaseModel):
    """RFC 7591 dynamic client registration request."""

    model_config = ConfigDict(frozen=True)

    redirect_uris: tuple[str, ...]
    client_name: str | None = None
    grant_types: tuple[str, ...] = ("authorization_code",)
    response_types: tuple[str, ...] = ("code",)
    token_endpoint_auth_method: str = "none"  # noqa: S105

    @field_validator("redirect_uris")
    @classmethod
    def _validate_redirect_uris(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for uri in v:
            parsed = urlparse(uri)
            if not parsed.scheme or not parsed.netloc:
                msg = f"Redirect URI must be an absolute URI: {uri}"
                raise ValueError(msg)
            is_localhost = parsed.hostname in ("localhost", "127.0.0.1", "::1")
            if parsed.scheme not in ("https", "http"):
                msg = f"Redirect URI must use HTTPS (or HTTP for localhost): {uri}"
                raise ValueError(msg)
            if parsed.scheme == "http" and not is_localhost:
                msg = f"HTTP redirect URIs are only allowed for localhost: {uri}"
                raise ValueError(msg)
        return v


class ClientRegistrationResponse(BaseModel):
    """RFC 7591 dynamic client registration response."""

    model_config = ConfigDict(frozen=True)

    client_id: str
    client_secret: str | None = None
    client_id_issued_at: int | None = None
    client_secret_expires_at: int | None = None
    redirect_uris: tuple[str, ...]
    grant_types: tuple[str, ...]
    response_types: tuple[str, ...]
    token_endpoint_auth_method: str
