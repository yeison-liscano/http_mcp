import logging
from typing import cast

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
from starlette.requests import Request

from server.server_interface import ServerInterface

LOGGER = logging.getLogger(__name__)


class BaseTransport:
    supported_versions = ("2024-11-05", "2025-03-26", "2025-06-18")
    supported_methods = ("initialize", "tools/list", "tools/call", "prompts/list")

    def __init__(self, server: ServerInterface) -> None:
        self._server = server

    async def _process_request(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> JSONRPCResponse | JSONRPCError:
        try:
            if message.method == "initialize":
                response, _ = self._handle_initialization(message)
                return response

            if message.method in self.supported_methods:
                if message.method.startswith("tools/"):
                    return await self._process_tools_request(message, request)
                if message.method.startswith("prompts/"):
                    return await self._process_prompts_request(message)

            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=ErrorData(
                    code=-32601,
                    message=f"Method not supported: {message.method}",
                ),
            )
        except Exception:
            LOGGER.exception("Error processing request")
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=ErrorData(
                    code=-32603,
                    message="Internal error",
                ),
            )

    def _handle_initialization(
        self,
        message: JSONRPCRequest,
    ) -> tuple[JSONRPCResponse | JSONRPCError, int]:
        protocol_version = message.params.get("protocolVersion") if message.params else None
        status_code = 200
        response: JSONRPCResponse | JSONRPCError

        if protocol_version in self.supported_versions:
            response = JSONRPCResponse(
                jsonrpc="2.0",
                id=message.id,
                result={
                    "protocolVersion": protocol_version,
                    "capabilities": self._server.capabilities.to_dict(),
                    "serverInfo": {"name": self._server.name, "version": self._server.version},
                },
            )
        else:
            LOGGER.error("Unsupported protocol version: %s", protocol_version)
            status_code = 400
            response = JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=ErrorData(
                    code=-32602,
                    message="Unsupported protocol version",
                    data={
                        "supported": list(self.supported_versions),
                        "requested": protocol_version,
                    },
                ),
            )
        return response, status_code

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
                cast(str, name),
                cast(dict, arguments),
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
        except Exception:
            LOGGER.exception("Error calling tool %s", name)
            return JSONRPCResponse(
                jsonrpc="2.0",
                id=message.id,
                # TODO(https://github.com/yeison-liscano/http_mcp/issues/2): # noqa: FIX002
                result=CallToolResult(
                    content=[TextContent(type="text", text="Error calling tool")],
                    structuredContent={},
                    isError=True,
                ).model_dump(),
            )
