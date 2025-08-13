import json
import logging

from pydantic import ValidationError
from starlette.requests import Request

from server.messages import (
    Error,
    InitializationRequest,
    InitializeResponse,
    InitializeResponseResult,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
    ServerInfo,
    TextContent,
)
from server.prompts import (
    PromptGetRequest,
    PromptsGetResponse,
    PromptsListResponse,
)
from server.server_interface import ServerInterface
from server.tools import (
    ToolsCallRequest,
    ToolsCallResponse,
    ToolsCallResult,
    ToolsListResponse,
    ToolsListResult,
)

LOGGER = logging.getLogger(__name__)


class BaseTransport:
    supported_versions = ("2024-11-05", "2025-03-26", "2025-06-18")
    supported_methods = ("initialize", "tools/list", "tools/call", "prompts/list", "prompts/get")

    def __init__(self, server: ServerInterface) -> None:
        self._server = server

    async def _process_request(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> JSONRPCMessage:
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
                error=Error(
                    code=-32601,
                    message=f"Method not supported: {message.method}",
                ),
            )
        except Exception:
            LOGGER.exception("Error processing request")
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
                    code=-32603,
                    message="Internal error",
                ),
            )

    def _handle_initialization(
        self,
        message: JSONRPCRequest,
    ) -> tuple[InitializeResponse | JSONRPCError, int]:
        try:
            message = InitializationRequest.model_validate(message.model_dump())
        except ValidationError as e:
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(code=-32600, message=json.dumps(e.errors())),
            ), 400
        protocol_version = message.params.protocol_version
        status_code = 200
        response: InitializeResponse | JSONRPCError

        if protocol_version in self.supported_versions:
            response = InitializeResponse(
                jsonrpc="2.0",
                id=message.id,
                result=InitializeResponseResult(
                    protocol_version=protocol_version,
                    capabilities=self._server.capabilities,
                    server_info=ServerInfo(name=self._server.name, version=self._server.version),
                ),
            )
        else:
            LOGGER.error("Unsupported protocol version: %s", protocol_version)
            status_code = 400
            response = JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
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
        self, message: JSONRPCRequest
    ) -> PromptsListResponse | JSONRPCError | PromptsGetResponse:
        if message.method == "prompts/list":
            result = self._server.list_prompts()
            return PromptsListResponse(
                jsonrpc="2.0",
                id=message.id,
                result=result,
            )
        if message.method == "prompts/get" and message.params:
            validated_message = PromptGetRequest.model_validate(message)
            prompt_result = await self._server.get_prompt(
                validated_message.params.name,
                validated_message.params.arguments,
            )
            return PromptsGetResponse(
                jsonrpc="2.0",
                id=message.id,
                result=prompt_result,
            )

        return JSONRPCError(
            jsonrpc="2.0",
            id=message.id,
            error=Error(
                code=-32601,
                message=f"Method not found: {message.method}",
            ),
        )

    async def _process_tools_request(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> JSONRPCMessage | JSONRPCError:
        if message.method == "tools/list":
            tools = await self._server.list_tools()
            return ToolsListResponse(
                jsonrpc="2.0",
                id=message.id,
                result=ToolsListResult(
                    tools=tools,
                    next_cursor="",
                ),
            )
        if message.method == "tools/call":
            return await self._call_tool(message, request)

        return JSONRPCError(
            jsonrpc="2.0",
            id=message.id,
            error=Error(
                code=-32601,
                message=f"Method not found: {message.method}",
            ),
        )

    async def _call_tool(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> ToolsCallResponse | JSONRPCError:
        try:
            message = ToolsCallRequest.model_validate(message.model_dump())
        except ValidationError as e:
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(code=-32600, message=json.dumps(e.errors())),
            )

        name = message.params.name
        arguments = message.params.arguments

        try:
            returned_value = await self._server.call_tool(
                name,
                arguments,
                request,
                self._server.context,
            )

            return ToolsCallResponse(
                jsonrpc="2.0",
                id=message.id,
                result=ToolsCallResult(
                    content=(TextContent(type="text", text=returned_value.model_dump_json()),),
                    is_error=False,
                    structured_content=returned_value.model_dump(mode="json"),
                ),
            )
        except Exception:
            LOGGER.exception("Error calling tool %s", name)
            return ToolsCallResponse(
                jsonrpc="2.0",
                id=message.id,
                result=ToolsCallResult(
                    content=(TextContent(type="text", text="Error calling tool"),),
                    is_error=True,
                ),
            )
