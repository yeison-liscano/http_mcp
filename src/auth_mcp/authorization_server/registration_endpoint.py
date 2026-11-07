import json
import logging
from http import HTTPStatus
from typing import assert_never

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from auth_mcp.authorization_server.client_store import ClientStore, RegistrationRejected
from auth_mcp.types.errors import OAuthErrorResponse
from auth_mcp.types.registration import (
    DISALLOWED_REDIRECT_SCHEMES,
    ClientRegistrationRequest,
    ClientRegistrationResponse,
)

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

    def __init__(
        self,
        client_store: ClientStore,
        allowed_custom_redirect_schemes: frozenset[str] | set[str] | tuple[str, ...] = (),
    ) -> None:
        normalized = frozenset(s.lower() for s in allowed_custom_redirect_schemes)
        conflicts = normalized & DISALLOWED_REDIRECT_SCHEMES
        if conflicts:
            msg = (
                "allowed_custom_redirect_schemes must not include disallowed "
                f"schemes: {sorted(conflicts)}"
            )
            raise ValueError(msg)
        for reserved in ("http", "https"):
            if reserved in normalized:
                msg = (
                    "allowed_custom_redirect_schemes must not include "
                    f"{reserved!r}; it is already handled by default rules"
                )
                raise ValueError(msg)
        self._client_store = client_store
        self._allowed_custom_redirect_schemes = normalized

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

        match self._parse_body(body):
            case Response() as rejection:
                return rejection
            case ClientRegistrationRequest() as registration_request:
                return await self._register(registration_request)
            case _ as unreachable:
                assert_never(unreachable)

    async def _register(self, registration_request: ClientRegistrationRequest) -> Response:
        try:
            outcome = await self._client_store.register_client(registration_request)
        except Exception:
            LOGGER.exception("Unexpected error during client registration")
            return _error_response(
                "Internal server error",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        match outcome:
            case RegistrationRejected(reason=reason):
                return _error_response(reason)
            case ClientRegistrationResponse() as registration_response:
                return Response(
                    content=json.dumps(
                        registration_response.model_dump(mode="json", exclude_none=True),
                    ).encode("utf-8"),
                    status_code=HTTPStatus.CREATED,
                    media_type="application/json",
                    headers=_SECURITY_HEADERS,
                )
            case _ as unreachable:
                assert_never(unreachable)

    def _parse_body(self, body: bytes) -> ClientRegistrationRequest | Response:
        try:
            return ClientRegistrationRequest.model_validate_json(
                body,
                context={
                    "allowed_custom_redirect_schemes": self._allowed_custom_redirect_schemes,
                },
            )
        except ValidationError as exc:
            return _error_response(str(exc.errors()[0]["msg"]))
