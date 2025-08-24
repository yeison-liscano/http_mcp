import json
import logging
from http import HTTPStatus

from pydantic import ValidationError
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from http_mcp._transport_base import BaseTransport
from http_mcp._transport_types import ErrorResponseInfo, ProtocolErrorCode
from http_mcp.mcp_types.messages import (
    Error,
    JSONRPCError,
    JSONRPCRequest,
)
from http_mcp.server_interface import ServerInterface

LOGGER = logging.getLogger(__name__)
MAXIMUM_MESSAGE_SIZE = 4 * 1024 * 1024  # 4MB


class HTTPTransport(BaseTransport):
    def __init__(self, server: ServerInterface) -> None:
        super().__init__(server)

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)

        if request.method == "POST":
            content_type = request.headers.get("content-type")
            # Not support for SSE
            if not content_type or "application/json" not in content_type:
                LOGGER.error("Unsupported Media Type: %s", content_type)
                await self._send_error_response(
                    send,
                    ErrorResponseInfo(
                        protocol_code=ProtocolErrorCode.INVALID_PARAMS,
                        http_status_code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                        message="Unsupported Media Type: Content-Type must be application/json",
                        headers={"Content-Type": "application/json"},
                    ),
                )
                return
            await self._handle_post_request(request, send)
        else:
            await self._handle_unsupported_request(send)

    async def _handle_post_request(self, request: Request, send: Send) -> None:
        body = await request.body()
        if len(body) > MAXIMUM_MESSAGE_SIZE:
            LOGGER.error("Request body too large")
            await self._send_error_response(
                send,
                ErrorResponseInfo(
                    protocol_code=ProtocolErrorCode.INVALID_PARAMS,
                    http_status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    message="Request body too large.",
                ),
            )
            return

        try:
            raw_message = json.loads(body)
        except json.JSONDecodeError:
            await self._send_error_response(
                send,
                ErrorResponseInfo(
                    protocol_code=ProtocolErrorCode.INVALID_PARAMS,
                    http_status_code=HTTPStatus.BAD_REQUEST,
                    message="Parse error: Invalid body",
                ),
            )
            return

        await self._handle_raw_message(raw_message, send, request)

    async def _handle_raw_message(
        self,
        raw_message: dict,
        send: Send,
        request: Request,
    ) -> None:
        try:
            if raw_message.get("method", "").startswith("notifications/"):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-type", b"application/json")],
                    },
                )

                await send(
                    {
                        "type": "http.response.body",
                        "body": b"",
                        "more_body": False,
                    },
                )
                return None

            request_message = JSONRPCRequest.model_validate(raw_message)
        except ValidationError:
            LOGGER.exception("Error validating message")
            is_invalid_method = raw_message.get("method", "") not in self.supported_methods
            await self._send_error_response(
                send,
                ErrorResponseInfo(
                    message_id=raw_message.get("id"),
                    protocol_code=(
                        ProtocolErrorCode.METHOD_NOT_FOUND
                        if is_invalid_method
                        else ProtocolErrorCode.INVALID_PARAMS
                    ),
                    http_status_code=HTTPStatus.BAD_REQUEST,
                    message="Error validating message request",
                ),
            )
            return None
        else:
            return await self._process_messages(request_message, send, request)

    async def _process_messages(
        self,
        message: JSONRPCRequest,
        send: Send,
        request: Request,
    ) -> None:
        response = await self._process_request(message, request)

        await send(
            {
                "type": "http.response.start",
                "status": HTTPStatus.OK.value,
                "headers": [
                    (b"content-type", b"application/json"),
                ],
            },
        )

        await send(
            {
                "type": "http.response.body",
                "body": response.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"),
                "more_body": False,
            },
        )

    async def _handle_unsupported_request(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": HTTPStatus.METHOD_NOT_ALLOWED.value,
                "headers": [
                    (b"allow", b"POST"),
                    (b"content-type", b"text/plain"),
                ],
            },
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"Method Not Allowed",
                "more_body": False,
            },
        )

    async def _send_error_response(
        self,
        send: Send,
        error_info: ErrorResponseInfo,
    ) -> None:
        error_response = JSONRPCError(
            jsonrpc="2.0",
            id=error_info.message_id,
            error=Error(
                code=error_info.protocol_code.value,
                message=error_info.message,
            ),
        )

        response_headers = [(b"content-type", b"application/json")]
        if error_info.headers:
            response_headers.extend(
                [(k.lower().encode(), v.encode()) for k, v in error_info.headers.items()],
            )

        await send(
            {
                "type": "http.response.start",
                "status": error_info.http_status_code.value,
                "headers": response_headers,
            },
        )

        await send(
            {
                "type": "http.response.body",
                "body": error_response.model_dump_json(by_alias=True, exclude_none=True).encode(
                    "utf-8",
                ),
                "more_body": False,
            },
        )
