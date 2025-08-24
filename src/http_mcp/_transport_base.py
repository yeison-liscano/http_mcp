import json
import logging
from http import HTTPStatus

from pydantic import ValidationError
from starlette.requests import Request

from http_mcp._transport_types import ProtocolErrorCode
from http_mcp.exceptions import ProtocolError, ServerError
from http_mcp.mcp_types.content import TextContent
from http_mcp.mcp_types.messages import (
    Error,
    InitializationRequest,
    InitializeResponse,
    InitializeResponseResult,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
    ServerInfo,
)
from http_mcp.mcp_types.prompts import (
    PromptGetRequest,
    PromptGetResult,
    PromptsGetResponse,
    PromptsListResponse,
)
from http_mcp.mcp_types.tools import (
    ToolsCallRequest,
    ToolsCallResponse,
    ToolsCallResult,
    ToolsListResponse,
    ToolsListResult,
)
from http_mcp.server_interface import ServerInterface

LOGGER = logging.getLogger(__name__)


class BaseTransport:
    supported_versions = ("2025-06-18",)
    supported_methods = ("initialize", "tools/list", "tools/call", "prompts/list", "prompts/get")

    def __init__(self, server: ServerInterface) -> None:
        self._server = server

    async def _process_request(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> JSONRPCMessage:
        if message.method == "initialize":
            response, _ = self._handle_initialization(message)
            return response
        if message.method.startswith("tools/"):
            return await self._process_tools_request(message, request)

        return await self._process_prompts_request(message, request)

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
                error=Error(
                    code=ProtocolErrorCode.INVALID_PARAMS.value,
                    message=json.dumps(e.errors()),
                ),
            ), HTTPStatus.BAD_REQUEST
        protocol_version = message.params.protocol_version
        status_code = HTTPStatus.OK
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
            status_code = HTTPStatus.BAD_REQUEST
            response = JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
                    code=ProtocolErrorCode.INVALID_PARAMS.value,
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
        request: Request,
    ) -> PromptsListResponse | JSONRPCError | PromptsGetResponse:
        if message.method == "prompts/list":
            result = self._server.list_prompts()
            return PromptsListResponse(
                jsonrpc="2.0",
                id=message.id,
                result=result,
            )

        try:
            validated_message = PromptGetRequest.model_validate(message.model_dump())
            prompt_result = await self._server.get_prompt(
                validated_message.params.name,
                validated_message.params.arguments,
                request,
            )
        except ServerError as e:
            return PromptsGetResponse(
                jsonrpc="2.0",
                id=message.id,
                result=PromptGetResult(
                    description=e.message,
                    messages=(),
                ),
            )
        except ProtocolError as e:
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
                    code=ProtocolErrorCode.INVALID_PARAMS.value,
                    message=e.message,
                ),
            )
        else:
            return PromptsGetResponse(
                jsonrpc="2.0",
                id=message.id,
                result=prompt_result,
            )

    async def _process_tools_request(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> JSONRPCMessage | JSONRPCError:
        if message.method == "tools/list":
            tools = self._server.list_tools()
            return ToolsListResponse(
                jsonrpc="2.0",
                id=message.id,
                result=ToolsListResult(
                    tools=tools,
                    next_cursor="",
                ),
            )

        return await self._call_tool(message, request)

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
                error=Error(
                    code=ProtocolErrorCode.INVALID_PARAMS.value,
                    message=json.dumps(e.errors()),
                ),
            )

        name = message.params.name
        arguments = message.params.arguments

        try:
            returned_value = await self._server.call_tool(
                name,
                arguments,
                request,
            )

            return ToolsCallResponse(
                jsonrpc="2.0",
                id=message.id,
                result=ToolsCallResult(
                    content=(
                        TextContent(
                            type="text",
                            text=returned_value.model_dump_json(by_alias=True),
                        ),
                    ),
                    is_error=False,
                    structured_content=returned_value.model_dump(mode="json", by_alias=True),
                ),
            )
        except ProtocolError as e:
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
                    code=ProtocolErrorCode.INVALID_PARAMS.value,
                    message=e.message,
                ),
            )
        except ServerError as e:
            LOGGER.exception("Error calling tool %s", name)
            return ToolsCallResponse(
                jsonrpc="2.0",
                id=message.id,
                result=ToolsCallResult(
                    content=(TextContent(type="text", text=e.message),),
                    is_error=True,
                ),
            )
