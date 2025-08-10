import asyncio
import json
import logging

from mcp.types import (
    CallToolResult,
    ErrorData,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    ListPromptsResult,
    ListToolsResult,
    TextContent,
    Tool,
)
from pydantic import ValidationError
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from server.server_interface import ServerInterface

LOGGER = logging.getLogger("interacts")
MAXIMUM_MESSAGE_SIZE = 4 * 1024 * 1024  # 4MB


class HTTPTransport:
    supported_versions = ("2024-11-05", "2025-03-26", "2025-06-18")

    def __init__(
        self,
        endpoint: str,
        version: str,
        name: str,
        server: ServerInterface,
    ) -> None:
        self._endpoint = endpoint
        self._version = version
        self._name = name
        self._server = server

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)

        if request.method == "POST":
            await self._handle_post_request(request, send)
        else:
            await self._handle_unsupported_request(send)

    async def _handle_post_request(self, request: Request, send: Send) -> None:
        content_type = request.headers.get("content-type", "")

        # we only support HTTP
        if not content_type or "application/json" not in content_type:
            return await self._send_error_response(
                send,
                -32000,
                "Unsupported Media Type: Content-Type must be application/json",
                415,
            )

        body = await request.body()
        if len(body) > MAXIMUM_MESSAGE_SIZE:
            return await self._send_error_response(
                send,
                -32000,
                f"Request body too large. Maximum size is {MAXIMUM_MESSAGE_SIZE} bytes.",
                413,
            )

        try:
            raw_message = json.loads(body)
        except json.JSONDecodeError:
            return await self._send_error_response(
                send,
                -32700,
                "Parse error: Invalid JSON",
                400,
            )

        return await self._handle_raw_message(raw_message, send, request)

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
                except ValidationError:
                    LOGGER.exception("Error")
                    return await self._send_error_response(
                        send,
                        -32700,
                        "Parse error",
                        400,
                    )
        else:
            try:
                if raw_message.get("method", "") == "initialize":
                    return await self._handle_initialization(
                        raw_message,
                        send,
                    )
                if not raw_message.get("method", "").startswith("notifications/"):
                    messages.append(JSONRPCRequest.model_validate(raw_message))
            except ValidationError:
                LOGGER.exception("Error")
                return await self._send_error_response(
                    send,
                    -32700,
                    "Error",
                    400,
                )

        return await self._process_messages(messages, send, request)

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
            return await send(
                {
                    "type": "http.response.body",
                    "body": responses[0].model_dump_json().encode("utf-8"),
                    "more_body": False,
                },
            )

        await send(
            {
                "type": "http.response.body",
                "body": json.dumps([response.model_dump() for response in responses]).encode(
                    "utf-8",
                ),
                "more_body": False,
            },
        )

        return None

    async def _handle_unsupported_request(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"allow", b"POST"),
                ],
            },
        )

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
            id=message,
            error=ErrorData(
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
                "body": error_response.model_dump_json().encode("utf-8"),
                "more_body": False,
            },
        )

    async def _call_tool(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> JSONRPCResponse | JSONRPCError:
        if not hasattr(message, "params") or not isinstance(message.params, dict):
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=ErrorData(
                    code=-32602,
                    message="Invalid params: expected an object with 'name' and 'arguments'",
                ),
            )

        name = message.params.get("name")
        arguments = message.params.get("arguments", {})

        if not name:
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=ErrorData(
                    code=-32602,
                    message="Invalid params: missing 'name'",
                ),
            )

        try:
            returned_value = await self._server.call_tool(
                name,
                arguments,
                request,
                self._server.context,
            )

            return JSONRPCResponse(
                jsonrpc="2.0",
                id=message.id,
                result=CallToolResult(
                    content=[TextContent(type="text", text=returned_value.model_dump_json())],
                    structuredContent=returned_value.model_dump(),
                    isError=False,
                ).model_dump(),
            )
        except Exception:  # noqa: BLE001
            LOGGER.error("Error calling tool %s", name)
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=ErrorData(
                    code=-32000,
                    message="Error calling tool",
                ),
            )

    async def _send_accept_response(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                ],
            },
        )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def _handle_initialization(self, message: dict, send: Send) -> None:
        message_id = message.get("id", 0)
        protocol_version = message.get("params", {}).get("protocolVersion")
        response: JSONRPCResponse | JSONRPCError | None = None

        if protocol_version in self.supported_versions:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                    ],
                },
            )

            response = JSONRPCResponse(
                jsonrpc="2.0",
                id=message_id,
                result={
                    "protocolVersion": protocol_version,
                    "capabilities": {
                        "experimental": {},
                        "prompts": {"listChanged": False},
                        "resources": {"listChanged": False},
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {"name": self._name, "version": self._version},
                },
            )

        else:
            LOGGER.error("Unsupported protocol version: %s", protocol_version)
            await send(
                {
                    "type": "http.response.start",
                    "status": 400,
                    "headers": [(b"content-type", b"application/json")],
                },
            )
            response = JSONRPCError(
                jsonrpc="2.0",
                id=message_id,
                error=ErrorData(
                    code=-32602,
                    message="Unsupported protocol version",
                    data={
                        "supportedVersions": list(self.supported_versions),
                        "requestedVersion": protocol_version,
                    },
                ),
            )

        await send(
            {
                "type": "http.response.body",
                "body": response.model_dump_json().encode("utf-8"),
                "more_body": False,
            },
        )

    async def _process_prompts_request(
        self,
        message: JSONRPCRequest,
    ) -> JSONRPCResponse | JSONRPCError:
        if message.method == "prompts/list":
            return JSONRPCResponse(
                jsonrpc="2.0",
                id=message.id,
                result=ListPromptsResult(
                    prompts=[],
                    nextCursor="",
                ).model_dump(),
            )

        return JSONRPCError(
            jsonrpc="2.0",
            id=message.id,
            error=ErrorData(
                code=-32601,
                message=f"Method not found: {message.method}",
            ),
        )

    async def _process_tools_request(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> JSONRPCResponse | JSONRPCError:
        if message.method == "tools/list":
            tools = await self._server.list_tools()
            return JSONRPCResponse(
                jsonrpc="2.0",
                id=message.id,
                result=ListToolsResult(
                    tools=[Tool.model_validate(_tool) for _tool in tools],
                    nextCursor="",
                ).model_dump(),
            )
        if message.method == "tools/call":
            return await self._call_tool(message, request)

        return JSONRPCError(
            jsonrpc="2.0",
            id=message.id,
            error=ErrorData(
                code=-32601,
                message=f"Method not found: {message.method}",
            ),
        )

    async def _process_request(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> JSONRPCResponse | JSONRPCError:
        try:
            if message.method.startswith("tools/"):
                return await self._process_tools_request(message, request)
            if message.method.startswith("prompts/"):
                return await self._process_prompts_request(message)

            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=ErrorData(
                    code=-32601,
                    message=f"Method not found: {message.method}",
                ),
            )
        except Exception as e:
            LOGGER.exception("Error processing request")
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=ErrorData(
                    code=-32603,
                    message=f"Internal error {e}",
                ),
            )
