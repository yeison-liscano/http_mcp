from http import HTTPStatus
from typing import Any

from starlette.authentication import AuthenticationError
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from auth_mcp.types.errors import OAuthErrorResponse, WWWAuthenticateChallenge


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
    """ASGI middleware that intercepts 401/403 responses and adds WWW-Authenticate headers.

    Wraps Starlette's AuthenticationMiddleware to produce standards-compliant
    OAuth 2.1 error responses with resource_metadata discovery parameter.
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

        status_code = 0
        original_headers: list[tuple[bytes, bytes]] = []

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code, original_headers

            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
                original_headers = list(message.get("headers", []))

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
                    original_headers.append(
                        (b"www-authenticate", www_auth.encode("utf-8")),
                    )
                    message = {
                        **message,
                        "headers": original_headers,
                    }

            await send(message)

        await self._app(scope, receive, send_wrapper)  # type: ignore[arg-type]


def on_auth_error(
    _conn: HTTPConnection,
    _exc: AuthenticationError,
) -> Response:
    """Error handler for Starlette's AuthenticationMiddleware.

    Returns a JSON response with an OAuth error body for 401 responses.
    The WWW-Authenticate header is added by AuthErrorMiddleware.
    """
    error_response = OAuthErrorResponse(
        error="invalid_token",
        error_description="Authentication required",
    )
    return JSONResponse(
        content=error_response.model_dump(exclude_none=True),
        status_code=HTTPStatus.UNAUTHORIZED,
    )
