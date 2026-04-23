import json
from http import HTTPStatus

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from auth_mcp.types.metadata import AuthorizationServerMetadata

_SECURITY_HEADERS: dict[str, str] = {
    "x-content-type-options": "nosniff",
    "cache-control": "no-store",
    "strict-transport-security": "max-age=31536000; includeSubDomains",
}


class AuthorizationServerMetadataEndpoint:
    """Serves the RFC 8414 Authorization Server Metadata document.

    Handles GET requests to /.well-known/oauth-authorization-server and returns
    the metadata JSON document.
    """

    def __init__(self, metadata: AuthorizationServerMetadata) -> None:
        self._metadata = metadata
        self._serialized = json.dumps(
            metadata.model_dump(mode="json", exclude_none=True),
        ).encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        if request.method != "GET":
            response = Response(
                content="Method Not Allowed",
                status_code=HTTPStatus.METHOD_NOT_ALLOWED,
                headers={"allow": "GET", **_SECURITY_HEADERS},
            )
            await response(scope, receive, send)
            return

        response = Response(
            content=self._serialized,
            status_code=HTTPStatus.OK,
            media_type="application/json",
            headers=_SECURITY_HEADERS,
        )
        await response(scope, receive, send)
