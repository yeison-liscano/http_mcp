from pydantic import BaseModel
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from server.models import Tool, TToolsArguments_co, TToolsContext, TToolsOutput_co
from server.server_interface import ServerInterface
from server.transport import HTTPTransport


class MCPServer(ServerInterface[TToolsContext]):
    def __init__(
        self,
        tools: tuple[Tool[TToolsArguments_co, TToolsContext, TToolsOutput_co], ...],
        name: str,
        version: str,
        endpoint: str,
        context: TToolsContext | None = None,
    ) -> None:
        self.version = version
        self._context = context
        self._tools = tools
        self._transport = HTTPTransport(endpoint, version, name, self)

    async def app(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._transport.handle_request(scope, receive, send)

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
