from http import HTTPStatus
from typing import Any

from starlette.authentication import AuthenticationError
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from auth_mcp.types.errors import OAuthErrorResponse, WWWAuthenticateChallenge

_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"cache-control", b"no-store"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
]


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
    On 401/403, additionally injects a WWW-Authenticate header with the
    resource_metadata discovery parameter per RFC 9728.
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
                    error = "invalid_token" if status_code == HTTPStatus.UNAUTHORIZED else None
                    www_auth = build_www_authenticate_header(
                        resource_metadata_url=self._resource_metadata_url,
                        realm=self._realm,
                        error=error,
                    )
                    headers.append(
                        (b"www-authenticate", www_auth.encode("utf-8")),
                    )

                message = {**message, "headers": headers}

            await send(message)

        await self._app(scope, receive, send_wrapper)  # type: ignore[arg-type]


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
