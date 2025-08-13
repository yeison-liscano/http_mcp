import asyncio
import json
import logging

from pydantic import ValidationError
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from server.messages import (
    Error,
    JSONRPCError,
    JSONRPCRequest,
)
from server.server_interface import ServerInterface
from server.transport_base import BaseTransport

LOGGER = logging.getLogger(__name__)
MAXIMUM_MESSAGE_SIZE = 4 * 1024 * 1024  # 4MB


class HTTPTransport(BaseTransport):
    def __init__(self, server: ServerInterface) -> None:
        super().__init__(server)

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)

        if request.method == "POST":
            await self._handle_post_request(request, send)
        else:
            await self._handle_unsupported_request(send)

    async def _handle_post_request(self, request: Request, send: Send) -> None:
        content_type = request.headers.get("content-type")

        # we only support HTTP
        if not content_type or "application/json" not in content_type:
            await self._send_error_response(
                send,
                -32000,
                "Unsupported Media Type: Content-Type must be application/json",
                415,
            )
            return

        body = await request.body()
        if len(body) > MAXIMUM_MESSAGE_SIZE:
            await self._send_error_response(
                send,
                -32000,
                f"Request body too large. Maximum size is {MAXIMUM_MESSAGE_SIZE} bytes.",
                413,
            )
            return

        try:
            raw_message = json.loads(body)
        except json.JSONDecodeError:
            await self._send_error_response(
                send,
                -32700,
                "Parse error: Invalid body",
                400,
            )
            return

        await self._handle_raw_message(raw_message, send, request)

    async def _handle_raw_message(
        self,
        raw_message: dict | list[dict],
        send: Send,
        request: Request,
    ) -> None:
        messages: list[JSONRPCRequest] = []
        if isinstance(raw_message, list):
            # An array batching
            for msg in raw_message:
                try:
                    if not msg.get("method", "").startswith("notifications/"):
                        messages.append(JSONRPCRequest.model_validate(msg))
                except ValidationError as e:
                    LOGGER.exception("Error validating message")
                    await self._send_error_response(
                        send,
                        -32700,
                        json.dumps(e.errors()),
                        400,
                    )
                    return
        else:
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
                    return
                request_message = JSONRPCRequest.model_validate(raw_message)
                if request_message.method == "initialize":
                    await self._handle_initialization_request(request_message, send)
                    return
                messages.append(request_message)
            except ValidationError:
                LOGGER.exception("Error validating message")
                await self._send_error_response(
                    send,
                    -32700,
                    "Error validating message request",
                    400,
                )
                return

        await self._process_messages(messages, send, request)

    async def _process_messages(
        self,
        messages: list[JSONRPCRequest],
        send: Send,
        request: Request,
    ) -> None:
        responses = await asyncio.gather(
            *[self._process_request(message, request) for message in messages],
        )

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                ],
            },
        )

        if len(responses) == 1:
            await send(
                {
                    "type": "http.response.body",
                    "body": responses[0]
                    .model_dump_json(by_alias=True, exclude_none=True)
                    .encode("utf-8"),
                    "more_body": False,
                },
            )
            return

        await send(
            {
                "type": "http.response.body",
                "body": json.dumps(
                    [
                        response.model_dump_json(by_alias=True, exclude_none=True)
                        for response in responses
                    ]
                ).encode(
                    "utf-8",
                ),
                "more_body": False,
            },
        )

    async def _handle_unsupported_request(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 405,
                "headers": [
                    (b"allow", b"POST"),
                ],
            },
        )
        await send({"type": "http.response.body", "body": b""})

    async def _send_error_response(
        self,
        send: Send,
        code: int,
        message: str,
        status_code: int = 400,
        headers: dict[str, str] | None = None,
    ) -> None:
        error_response = JSONRPCError(
            jsonrpc="2.0",
            id=0,
            error=Error(
                code=code,
                message=message,
            ),
        )

        response_headers = [(b"content-type", b"application/json")]
        if headers:
            response_headers.extend([(k.lower().encode(), v.encode()) for k, v in headers.items()])

        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": response_headers,
            },
        )

        await send(
            {
                "type": "http.response.body",
                "body": error_response.model_dump_json(by_alias=True, exclude_none=True).encode(
                    "utf-8"
                ),
                "more_body": False,
            },
        )

    async def _handle_initialization_request(self, message: JSONRPCRequest, send: Send) -> None:
        response, status_code = self._handle_initialization(message)

        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [(b"content-type", b"application/json")],
            },
        )
        await send(
            {
                "type": "http.response.body",
                "body": response.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"),
                "more_body": False,
            },
        )
