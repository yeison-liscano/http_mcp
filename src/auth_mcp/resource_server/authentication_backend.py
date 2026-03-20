import logging
import re

from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    BaseUser,
    SimpleUser,
    UnauthenticatedUser,
)
from starlette.requests import HTTPConnection

from auth_mcp.resource_server.token_validator import TokenValidator

LOGGER = logging.getLogger(__name__)

_AUTH_REQUIRED_MSG = "Authentication required"
_INVALID_SCHEME_MSG = "Invalid authorization scheme"
_INVALID_TOKEN_MSG = "Invalid or expired token"  # noqa: S105
_MALFORMED_TOKEN_MSG = "Malformed bearer token"  # noqa: S105

_MAX_TOKEN_LENGTH = 2048
_BEARER_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9\-._~+/]+=*$")


class OAuthAuthenticationBackend(AuthenticationBackend):
    """Starlette AuthenticationBackend that validates OAuth 2.1 Bearer tokens.

    Extracts Bearer token from the Authorization header, validates it using
    the provided TokenValidator, and returns AuthCredentials with the token's scopes.
    Compatible with http_mcp's has_required_scope() calls.

    When ``require_authentication`` is True (default), raises ``AuthenticationError``
    for missing or invalid tokens, causing Starlette's middleware to return 401.
    When False, unauthenticated requests are allowed through with empty credentials.
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
        auth_header = conn.headers.get("Authorization")
        if not auth_header:
            if self._require_authentication:
                raise AuthenticationError(_AUTH_REQUIRED_MSG)
            return AuthCredentials(), UnauthenticatedUser()

        parts = auth_header.split(" ", maxsplit=1)
        if len(parts) != 2 or parts[0].lower() != "bearer":  # noqa: PLR2004
            if self._require_authentication:
                raise AuthenticationError(_INVALID_SCHEME_MSG)
            return AuthCredentials(), UnauthenticatedUser()

        token = parts[1]
        if len(token) > _MAX_TOKEN_LENGTH or not _BEARER_TOKEN_PATTERN.match(token):
            LOGGER.debug("Malformed or oversized bearer token rejected")
            if self._require_authentication:
                raise AuthenticationError(_MALFORMED_TOKEN_MSG)
            return AuthCredentials(), UnauthenticatedUser()

        try:
            token_info = await self._token_validator.validate_token(token, self._resource_uri)
        except Exception:
            LOGGER.exception("Token validation raised an unexpected error")
            token_info = None
        if token_info is None:
            LOGGER.debug("Token validation failed")
            if self._require_authentication:
                raise AuthenticationError(_INVALID_TOKEN_MSG)
            return AuthCredentials(), UnauthenticatedUser()

        return AuthCredentials(list(token_info.scopes)), SimpleUser(token_info.subject)
