from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

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


@dataclass(frozen=True)
class RedirectUriViolation:
    reason: str
    type: Literal["redirect_uri_violation"] = "redirect_uri_violation"


class ClientRegistrationRequest(BaseModel):
    """RFC 7591 dynamic client registration request.

    Redirect URI validation accepts ``https`` unconditionally, ``http`` only
    for ``localhost`` / ``127.0.0.1`` / ``::1``, and any custom scheme listed
    in the ``allowed_custom_redirect_schemes`` validation context entry
    (RFC 8252 — OAuth 2.0 for Native Apps). Schemes in
    :data:`DISALLOWED_REDIRECT_SCHEMES` are always rejected, as is any URI carrying
    a fragment (RFC 6749 3.1.2). At least one redirect URI is required.
    """

    model_config = ConfigDict(frozen=True)

    # RFC 7591: a client using the authorization_code grant must register at least
    # one redirect URI, or the authorization server has nothing to match against.
    redirect_uris: Annotated[tuple[str, ...], Field(min_length=1)]
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
            violation = _find_redirect_uri_violation(uri, allowed_custom)
            if violation is not None:
                # Raising is how a pydantic validator reports invalid input.
                raise ValueError(violation.reason)
        return v


_LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})


def _find_redirect_uri_violation(  # noqa: PLR0911
    uri: str,
    allowed_custom: frozenset[str],
) -> RedirectUriViolation | None:
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    not_absolute = RedirectUriViolation(f"Redirect URI must be an absolute URI: {uri}")
    match scheme:
        case "":
            return not_absolute
        # SECURITY: the denylist check MUST stay above the allowlist and fragment checks below.
        # Callers can pass ``allowed_custom_redirect_schemes`` via Pydantic context,
        # and the endpoint's ``__init__`` guards against known-dangerous entries,
        # but this validator is the authoritative gate — do not reorder.
        case _ if scheme in DISALLOWED_REDIRECT_SCHEMES:
            return RedirectUriViolation(f"Redirect URI scheme is not allowed: {uri}")
        # RFC 6749 3.1.2: redirection endpoint URIs must not include a fragment.
        case _ if parsed.fragment:
            return RedirectUriViolation(f"Redirect URI must not contain a fragment: {uri}")
        case "https" | "http" if not parsed.netloc:
            return not_absolute
        case "http" if parsed.hostname not in _LOOPBACK_HOSTS:
            return RedirectUriViolation(f"HTTP redirect URIs are only allowed for localhost: {uri}")
        case "https" | "http":
            return None
        # Custom URI scheme (RFC 8252). Only accepted when the library caller has
        # explicitly opted this scheme in.
        case _ if scheme not in allowed_custom:
            return RedirectUriViolation(
                "Redirect URI must use HTTPS (or HTTP for localhost), "
                f"or a scheme explicitly allowed by the server: {uri}",
            )
        case _:
            return None if parsed.netloc or parsed.path else not_absolute


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
