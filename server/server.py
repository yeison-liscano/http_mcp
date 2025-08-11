from pydantic import BaseModel
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from server.models import (
    Capability,
    ServerCapabilities,
    Tool,
    TToolsArguments_co,
    TToolsContext,
    TToolsOutput_co,
)
from server.server_interface import ServerInterface
from server.stdio_transport import StdioTransport
from server.transport import HTTPTransport


class MCPServer(ServerInterface[TToolsContext]):
    def __init__(
        self,
        name: str,
        version: str,
        tools: tuple[Tool[TToolsArguments_co, TToolsContext, TToolsOutput_co], ...],
        context: TToolsContext,
    ) -> None:
        self._version = version
        self._name = name
        self._context = context
        self._tools = tools
        self._http_transport = HTTPTransport(self)
        self._stdio_transport = StdioTransport(self)

    async def app(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._http_transport.handle_request(scope, receive, send)

    async def serve_stdio(self, request_headers: dict[str, str] | None = None) -> None:
        await self._stdio_transport.start(request_headers)

    async def call_tool(
        self,
        tool_name: str,
        args: dict,
        request: Request,
        context: TToolsContext,
    ) -> BaseModel:
        tool = next(_tool for _tool in self._tools if _tool.name == tool_name)
        return await tool.invoque(args, request, context)

    async def list_tools(self) -> tuple[dict, ...]:
        return tuple(_tool.generate_json_schema() for _tool in self._tools)

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
            prompts=None,
            tools=capability if self._tools else None,
        )
