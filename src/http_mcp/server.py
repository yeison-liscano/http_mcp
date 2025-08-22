from pydantic import BaseModel
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from http_mcp.exceptions import PromptNotFoundError, ToolNotFoundError
from http_mcp.http_transport import HTTPTransport
from http_mcp.mcp_types.capabilities import Capability, ServerCapabilities
from http_mcp.mcp_types.prompts import PromptGetResult, PromptListResult
from http_mcp.prompts import Prompt
from http_mcp.server_interface import ServerInterface
from http_mcp.stdio_transport import StdioTransport
from http_mcp.tools import (
    TArguments_contra,
    Tool,
    TOutput_contra,
)


class MCPServer[TToolsContext](ServerInterface[TToolsContext]):
    def __init__(
        self,
        name: str,
        version: str,
        tools: tuple[Tool[TArguments_contra, TToolsContext, TOutput_contra], ...] = (),
        prompts: tuple[Prompt, ...] = (),
        context: TToolsContext | None = None,
    ) -> None:
        self._version = version
        self._name = name
        self._context = context
        self._tools = tools
        self._prompts = prompts
        self._http_transport = HTTPTransport(self)
        self._stdio_transport = StdioTransport(self)

    async def app(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._http_transport.handle_request(scope, receive, send)

    async def serve_stdio(self, request_headers: dict[str, str] | None = None) -> None:
        await self._stdio_transport.start(request_headers)

    @property
    def context(self) -> TToolsContext | None:
        return self._context

    @property
    def version(self) -> str:
        return self._version

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ServerCapabilities:
        capability = Capability(list_changed=False, subscribe=False)
        return ServerCapabilities(
            prompts=capability if self._prompts else None,
            tools=capability if self._tools else None,
        )

    def list_tools(self) -> tuple[dict, ...]:
        return tuple(_tool.generate_json_schema() for _tool in self._tools)

    async def call_tool(
        self,
        tool_name: str,
        args: dict,
        request: Request,
        context: TToolsContext,
    ) -> BaseModel:
        try:
            tool = next(_tool for _tool in self._tools if _tool.name == tool_name)
        except StopIteration as e:
            raise ToolNotFoundError(tool_name) from e
        return await tool.invoke(args, request, context)

    def list_prompts(self) -> PromptListResult:
        return PromptListResult(
            prompts=tuple(_prompt.to_prompt_protocol_object() for _prompt in self._prompts),
            next_cursor=None,
        )

    async def get_prompt(self, prompt_name: str, arguments: dict) -> PromptGetResult:
        try:
            _prompt = next(_prompt for _prompt in self._prompts if _prompt.name == prompt_name)
        except StopIteration as e:
            raise PromptNotFoundError(prompt_name) from e
        result = await _prompt.invoke(arguments)
        return PromptGetResult(
            description=_prompt.description,
            messages=result,
        )
