from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

# Schemes that must never be accepted as redirect URIs. ``javascript`` and
# ``data`` are XSS vectors; the others are non-web or non-navigable schemes
# that make no sense as OAuth redirect targets. This set is non-negotiable:
# callers cannot opt these back in via ``allowed_custom_redirect_schemes``.
DISALLOWED_REDIRECT_SCHEMES: frozenset[str] = frozenset(
    {
        "javascript",
        "data",
        "file",
        "vbscript",
        "about",
        "blob",
        "mailto",
        "tel",
        "ws",
        "wss",
        "ftp",
        "ftps",
        # Android intent scheme — can launch arbitrary activities with
        # attacker-controlled extras (e.g.
        # ``intent://evil#Intent;scheme=http;S.browser_fallback_url=...;end``).
        "intent",
        # Browser source-viewer pseudo-scheme.
        "view-source",
    },
)


class ClientRegistrationRequest(BaseModel):
    """RFC 7591 dynamic client registration request.

    Redirect URI validation accepts ``https`` unconditionally, ``http`` only
    for ``localhost`` / ``127.0.0.1`` / ``::1``, and any custom scheme listed
    in the ``allowed_custom_redirect_schemes`` validation context entry
    (RFC 8252 — OAuth 2.0 for Native Apps). Schemes in
    :data:`DISALLOWED_REDIRECT_SCHEMES` are always rejected.
    """

    model_config = ConfigDict(frozen=True)

    redirect_uris: tuple[str, ...]
    client_name: str | None = None
    grant_types: tuple[str, ...] = ("authorization_code",)
    response_types: tuple[str, ...] = ("code",)
    token_endpoint_auth_method: str = "none"  # noqa: S105

    @field_validator("redirect_uris")
    @classmethod
    def _validate_redirect_uris(
        cls,
        v: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        allowed_custom: frozenset[str] = frozenset()
        if info.context is not None:
            raw = info.context.get("allowed_custom_redirect_schemes")
            if raw is not None:
                allowed_custom = frozenset(s.lower() for s in raw)
        for uri in v:
            _validate_single_redirect_uri(uri, allowed_custom)
        return v


def _validate_single_redirect_uri(uri: str, allowed_custom: frozenset[str]) -> None:
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    if not scheme:
        msg = f"Redirect URI must be an absolute URI: {uri}"
        raise ValueError(msg)
    # SECURITY: the denylist check MUST stay above the allowlist check below.
    # Callers can pass ``allowed_custom_redirect_schemes`` via Pydantic context,
    # and the endpoint's ``__init__`` guards against known-dangerous entries,
    # but this validator is the authoritative gate — do not reorder.
    if scheme in DISALLOWED_REDIRECT_SCHEMES:
        msg = f"Redirect URI scheme is not allowed: {uri}"
        raise ValueError(msg)
    if scheme == "https":
        if not parsed.netloc:
            msg = f"Redirect URI must be an absolute URI: {uri}"
            raise ValueError(msg)
        return
    if scheme == "http":
        if not parsed.netloc:
            msg = f"Redirect URI must be an absolute URI: {uri}"
            raise ValueError(msg)
        if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            msg = f"HTTP redirect URIs are only allowed for localhost: {uri}"
            raise ValueError(msg)
        return
    # Custom URI scheme (RFC 8252). Only accepted when the library caller has
    # explicitly opted this scheme in.
    if scheme not in allowed_custom:
        msg = (
            "Redirect URI must use HTTPS (or HTTP for localhost), "
            f"or a scheme explicitly allowed by the server: {uri}"
        )
        raise ValueError(msg)
    if not parsed.netloc and not parsed.path:
        msg = f"Redirect URI must be an absolute URI: {uri}"
        raise ValueError(msg)


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
