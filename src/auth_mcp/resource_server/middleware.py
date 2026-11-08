import re
from http import HTTPStatus
from typing import Any

from starlette.authentication import AuthenticationError
from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from auth_mcp.types.errors import OAuthErrorResponse, WWWAuthenticateChallenge

_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"cache-control", b"no-store"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
]
_WWW_AUTHENTICATE = b"www-authenticate"
# The `scope` parameter of a challenge the wrapped app sent, such as the one the MCP
# transport attaches to a 403 naming the scopes the call needs.
_CHALLENGE_SCOPE = re.compile(rb'scope="([^"\\]*)"')


def _presents_bearer_credentials(scope: Scope) -> bool:
    """Report whether the request carried a Bearer token, valid or not."""
    authorization = Headers(scope=scope).get("authorization")
    if authorization is None:
        return False
    return authorization.split(" ", maxsplit=1)[0].lower() == "bearer"


def _challenge_scope(headers: list[tuple[bytes, bytes]]) -> str | None:
    """Return the scope a challenge from the wrapped app names, if it names one."""
    for name, value in headers:
        if name.lower() == _WWW_AUTHENTICATE:
            match = _CHALLENGE_SCOPE.search(value)
            if match is not None:
                return match.group(1).decode("latin-1")
    return None


def build_www_authenticate_header(
    resource_metadata_url: str,
    realm: str | None = None,
    scope: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> str:
    """Build a WWW-Authenticate header value per RFC 9728."""
    challenge = WWWAuthenticateChallenge(
        realm=realm,
        resource_metadata=resource_metadata_url,
        scope=scope,
        error=error,
        error_description=error_description,
    )
    return challenge.to_header_value()


class AuthErrorMiddleware:
    """ASGI middleware that adds security headers and WWW-Authenticate on 401/403.

    Adds security headers (nosniff, no-store, HSTS) to all HTTP responses.
    On 401/403, additionally sets a WWW-Authenticate header with the
    resource_metadata discovery parameter per RFC 9728.

    A 401 to a request that presented no Bearer token carries no ``error`` (RFC 6750
    section 3.1): the client did not know authentication was needed, so there is no
    token to call invalid. A 403 keeps the ``scope`` the wrapped app named, which is
    what lets the client step up to a token with the missing scopes.
    """

    def __init__(
        self,
        app: ASGIApp,
        resource_metadata_url: str,
        realm: str | None = None,
    ) -> None:
        self._app = app
        self._resource_metadata_url = resource_metadata_url
        self._realm = realm

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
                headers = list(message.get("headers", []))

                existing_names = {h[0] for h in headers}
                headers.extend(h for h in _SECURITY_HEADERS if h[0] not in existing_names)

                if status_code in (
                    HTTPStatus.UNAUTHORIZED,
                    HTTPStatus.FORBIDDEN,
                ):
                    www_auth = self._challenge(status_code, scope, _challenge_scope(headers))
                    # One complete challenge replaces whatever the app sent.
                    headers = [h for h in headers if h[0].lower() != _WWW_AUTHENTICATE]
                    headers.append((_WWW_AUTHENTICATE, www_auth.encode("ascii")))

                message = {**message, "headers": headers}

            await send(message)

        await self._app(scope, receive, send_wrapper)  # type: ignore[arg-type]

    def _challenge(self, status_code: int, scope: Scope, required_scope: str | None) -> str:
        if status_code == HTTPStatus.FORBIDDEN:
            error: str | None = "insufficient_scope"
        elif _presents_bearer_credentials(scope):
            error = "invalid_token"
        else:
            error = None
        return build_www_authenticate_header(
            resource_metadata_url=self._resource_metadata_url,
            realm=self._realm,
            scope=required_scope if status_code == HTTPStatus.FORBIDDEN else None,
            error=error,
        )


def on_auth_error(
    _conn: HTTPConnection,
    _exc: AuthenticationError,
) -> Response:
    """Error handler for Starlette's AuthenticationMiddleware.

    Returns a JSON response with an OAuth error body for 401 responses.
    Security headers and WWW-Authenticate are added by AuthErrorMiddleware.
    """
    error_response = OAuthErrorResponse(
        error="invalid_token",
        error_description="Authentication required",
    )
    return JSONResponse(
        content=error_response.model_dump(exclude_none=True),
        status_code=HTTPStatus.UNAUTHORIZED,
    )
