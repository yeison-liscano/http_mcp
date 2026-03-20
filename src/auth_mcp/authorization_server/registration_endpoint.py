import json
import logging
from http import HTTPStatus

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from auth_mcp.authorization_server.client_store import ClientStore
from auth_mcp.exceptions import RegistrationError
from auth_mcp.types.errors import OAuthErrorResponse
from auth_mcp.types.registration import ClientRegistrationRequest

LOGGER = logging.getLogger(__name__)

_MAX_BODY_SIZE = 64 * 1024  # 64 KB

_SECURITY_HEADERS: dict[str, str] = {
    "x-content-type-options": "nosniff",
    "cache-control": "no-store",
    "strict-transport-security": "max-age=31536000; includeSubDomains",
}


def _error_response(
    description: str,
    status_code: int = HTTPStatus.BAD_REQUEST,
) -> Response:
    error = OAuthErrorResponse(
        error="invalid_client_metadata",
        error_description=description,
    )
    return Response(
        content=json.dumps(
            error.model_dump(mode="json", exclude_none=True),
        ).encode("utf-8"),
        status_code=status_code,
        media_type="application/json",
        headers=_SECURITY_HEADERS,
    )


class DynamicClientRegistrationEndpoint:
    """RFC 7591 Dynamic Client Registration endpoint.

    Handles POST requests to register new OAuth clients. Validates the request
    body as a ``ClientRegistrationRequest`` and delegates to a ``ClientStore``.
    """

    def __init__(self, client_store: ClientStore) -> None:
        self._client_store = client_store

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        if request.method != "POST":
            response = Response(
                content="Method Not Allowed",
                status_code=HTTPStatus.METHOD_NOT_ALLOWED,
                headers={"allow": "POST", **_SECURITY_HEADERS},
            )
            await response(scope, receive, send)
            return

        response = await self._handle_registration(request)
        await response(scope, receive, send)

    async def _handle_registration(self, request: Request) -> Response:
        content_type = request.headers.get("content-type", "")
        if "application/json" not in content_type:
            return _error_response("Content-Type must be application/json")

        body = await request.body()
        if len(body) > _MAX_BODY_SIZE:
            return _error_response("Request body too large")

        registration_request = self._parse_body(body)
        if isinstance(registration_request, Response):
            return registration_request

        try:
            registration_response = await self._client_store.register_client(
                registration_request,
            )
        except RegistrationError as exc:
            return _error_response(exc.message)
        except Exception:
            LOGGER.exception("Unexpected error during client registration")
            return _error_response(
                "Internal server error",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return Response(
            content=json.dumps(
                registration_response.model_dump(mode="json", exclude_none=True),
            ).encode("utf-8"),
            status_code=HTTPStatus.CREATED,
            media_type="application/json",
            headers=_SECURITY_HEADERS,
        )

    @staticmethod
    def _parse_body(body: bytes) -> ClientRegistrationRequest | Response:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _error_response("Invalid JSON")

        try:
            return ClientRegistrationRequest.model_validate(data)
        except ValidationError as exc:
            return _error_response(str(exc.errors()[0]["msg"]))
