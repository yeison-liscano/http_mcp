import re
import unicodedata
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


# OAuth 2.1 removed the implicit and password grants, and the token endpoint models in
# `auth_mcp.types.oauth` serve these two only.
GrantType = Literal["authorization_code", "refresh_token"]
ResponseType = Literal["code"]
# RFC 7591 section 2 and the IANA "OAuth Token Endpoint Authentication Methods" registry.
TokenEndpointAuthMethod = Literal[
    "none",
    "client_secret_basic",
    "client_secret_post",
    "client_secret_jwt",
    "private_key_jwt",
]

_MAX_CLIENT_NAME_LENGTH = 256
# Whitespace, ASCII control characters and backslash. Python's URL parser and a browser's
# disagree on all of them: `urlparse` reads `http://evil.example\@localhost/` as host
# `localhost`, while the WHATWG parser ends the authority at the backslash and goes to
# `evil.example`.
_UNSAFE_URI_CHARACTERS = re.compile(r"[\x00-\x20\x7f\\]")


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
    a fragment (RFC 6749 3.1.2). At least one redirect URI is required. URIs containing
    whitespace, control characters, a backslash, or user information are rejected, as
    parsers disagree about where such URIs point.

    ``grant_types``, ``response_types`` and ``token_endpoint_auth_method`` accept only
    the values this package serves, and ``client_name`` is limited in length and may not
    contain control or formatting characters, since consent screens display it.
    """

    model_config = ConfigDict(frozen=True)

    # RFC 7591: a client using the authorization_code grant must register at least
    # one redirect URI, or the authorization server has nothing to match against.
    redirect_uris: Annotated[tuple[str, ...], Field(min_length=1)]
    client_name: Annotated[str, Field(max_length=_MAX_CLIENT_NAME_LENGTH)] | None = None
    grant_types: tuple[GrantType, ...] = ("authorization_code",)
    response_types: tuple[ResponseType, ...] = ("code",)
    token_endpoint_auth_method: TokenEndpointAuthMethod = "none"  # noqa: S105

    @field_validator("client_name")
    @classmethod
    def _validate_client_name(cls, v: str | None) -> str | None:
        # Categories C* (control, format, surrogate, private use, unassigned) and the
        # line and paragraph separators. Format characters include the bidirectional
        # overrides that can make a consent screen show a different name.
        if v is not None and any(
            unicodedata.category(char)[0] == "C" or unicodedata.category(char) in ("Zl", "Zp")
            for char in v
        ):
            msg = "client_name must not contain control or formatting characters"
            # Raising is how a pydantic validator reports invalid input.
            raise ValueError(msg)
        return v

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
        case _ if _UNSAFE_URI_CHARACTERS.search(uri):
            return RedirectUriViolation(
                "Redirect URI must not contain whitespace, control characters or "
                f"backslashes: {uri!r}",
            )
        # Userinfo has no place in a redirect URI, and it is how `user@host` spellings
        # make a URI look like it points somewhere it does not.
        case _ if "@" in parsed.netloc:
            return RedirectUriViolation(f"Redirect URI must not contain user information: {uri}")
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
