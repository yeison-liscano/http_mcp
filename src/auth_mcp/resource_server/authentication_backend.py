import logging
import re
import time
from dataclasses import dataclass
from typing import Literal, assert_never
from urllib.parse import urlsplit

from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    BaseUser,
    SimpleUser,
    UnauthenticatedUser,
)
from starlette.requests import HTTPConnection

from auth_mcp.resource_server.token_validator import TokenInfo, TokenValidator

LOGGER = logging.getLogger(__name__)

_AUTH_REQUIRED_MSG = "Authentication required"
_INVALID_SCHEME_MSG = "Invalid authorization scheme"
_INVALID_TOKEN_MSG = "Invalid or expired token"  # noqa: S105
_MALFORMED_TOKEN_MSG = "Malformed bearer token"  # noqa: S105

_MAX_TOKEN_LENGTH = 2048
# `\Z`, not `$`: Python's `$` also matches immediately before a trailing newline, so
# `$` here would pass a token ending in "\n" through to the validator. An HTTP parser
# rejects a bare LF in a header value long before this runs, but this backend is a
# reusable component and the token it blesses is handed to arbitrary validator code.
_BEARER_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9\-._~+/]+=*\Z")


def _canonical_resource(uri: str) -> tuple[str, str, str, str] | None:
    """Return the parts of a resource URI that identify it, or None if it does not parse.

    Scheme and host compare case-insensitively and a trailing slash is not significant,
    so `https://MCP.example.com/` and `https://mcp.example.com` name one resource.
    """
    try:
        parts = urlsplit(uri)
    except ValueError:
        return None
    return (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query)


def _is_for_resource(audience: str, resource_uri: str) -> bool:
    canonical = _canonical_resource(audience)
    return canonical is not None and canonical == _canonical_resource(resource_uri)


@dataclass(frozen=True)
class _CredentialsAbsent:
    type: Literal["credentials_absent"] = "credentials_absent"


@dataclass(frozen=True)
class _CredentialsRejected:
    reason: str
    type: Literal["credentials_rejected"] = "credentials_rejected"


class OAuthAuthenticationBackend(AuthenticationBackend):
    """Starlette AuthenticationBackend that validates OAuth 2.1 Bearer tokens.

    Extracts Bearer token from the Authorization header, validates it using
    the provided TokenValidator, and returns AuthCredentials with the token's scopes.
    Compatible with http_mcp's has_required_scope() calls.

    When ``require_authentication`` is True (default), raises ``AuthenticationError``
    for missing or invalid tokens, causing Starlette's middleware to return 401.
    When False, requests without credentials are allowed through with empty credentials.
    Presented invalid credentials are always rejected.

    Whatever the validator checked, the backend also refuses a token whose
    ``expires_at`` has passed, or whose ``audience`` is set and names a resource other
    than ``resource_uri`` (RFC 8707): a validator that forgot either check would
    otherwise accept a stale token, or one issued for another server.
    """

    def __init__(
        self,
        token_validator: TokenValidator,
        resource_uri: str,
        *,
        require_authentication: bool = True,
    ) -> None:
        self._token_validator = token_validator
        self._resource_uri = resource_uri
        self._require_authentication = require_authentication

    async def authenticate(self, conn: HTTPConnection) -> tuple[AuthCredentials, BaseUser]:
        match await self._verify_credentials(conn.headers.get("Authorization")):
            case TokenInfo() as token_info:
                return AuthCredentials(list(token_info.scopes)), SimpleUser(token_info.subject)
            case _CredentialsAbsent():
                if self._require_authentication:
                    # Raising is how Starlette's backend contract rejects a request.
                    raise AuthenticationError(_AUTH_REQUIRED_MSG)
                return AuthCredentials(), UnauthenticatedUser()
            case _CredentialsRejected(reason=reason):
                raise AuthenticationError(reason)
            case _ as unreachable:
                assert_never(unreachable)

    async def _verify_credentials(
        self,
        auth_header: str | None,
    ) -> TokenInfo | _CredentialsAbsent | _CredentialsRejected:
        if auth_header is None:
            return _CredentialsAbsent()

        parts = auth_header.split(" ", maxsplit=1)
        if len(parts) != 2 or parts[0].lower() != "bearer":  # noqa: PLR2004
            return _CredentialsRejected(_INVALID_SCHEME_MSG)

        token = parts[1]
        if len(token) > _MAX_TOKEN_LENGTH or not _BEARER_TOKEN_PATTERN.match(token):
            LOGGER.debug("Malformed or oversized bearer token rejected")
            return _CredentialsRejected(_MALFORMED_TOKEN_MSG)

        try:
            token_info = await self._token_validator.validate_token(token, self._resource_uri)
        except Exception:
            LOGGER.exception("Token validation raised an unexpected error")
            token_info = None
        if token_info is None:
            LOGGER.debug("Token validation failed")
            return _CredentialsRejected(_INVALID_TOKEN_MSG)

        return self._check_validity(token_info)

    def _check_validity(self, token_info: TokenInfo) -> TokenInfo | _CredentialsRejected:
        """Refuse a token the validator accepted that is expired or meant for elsewhere."""
        if token_info.expires_at is not None and token_info.expires_at <= time.time():
            LOGGER.debug("Expired token rejected")
            return _CredentialsRejected(_INVALID_TOKEN_MSG)
        if token_info.audience is not None and not _is_for_resource(
            token_info.audience,
            self._resource_uri,
        ):
            LOGGER.debug("Token issued for another resource rejected")
            return _CredentialsRejected(_INVALID_TOKEN_MSG)
        return token_info
