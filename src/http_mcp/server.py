from pydantic import BaseModel
from starlette.authentication import has_required_scope
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from http_mcp._mcp_types.capabilities import Capability, ServerCapabilities
from http_mcp._mcp_types.prompts import PromptGetResult, PromptListResult
from http_mcp._mcp_types.results import CacheScope
from http_mcp._stdio_transport import StdioTransport
from http_mcp._transport_http import HTTPTransport
from http_mcp.exceptions import InsufficientScopeError, PromptNotFoundError, ToolNotFoundError
from http_mcp.server_interface import ServerInterface
from http_mcp.types import Prompt, Tool

DEFAULT_CACHE_TTL_MS = 300_000


def _check_scope(request: Request, scopes: tuple[str, ...]) -> bool:
    """Check scopes, failing closed when no authentication backend is installed.

    Scoped tools/prompts are hidden and denied instead of raising when
    AuthenticationMiddleware is missing (e.g. STDIO transport).
    """
    if not scopes:
        return True
    if "auth" not in request.scope:
        return False
    return has_required_scope(request, scopes)


def _ensure_unique_names(feature_type: str, names: tuple[str, ...]) -> None:
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        msg = f"Duplicate {feature_type} names are not allowed: {duplicates}"
        raise ValueError(msg)


class MCPServer(ServerInterface):
    """An MCP server exposing Python functions as tools and prompts.

    Args:
        name: Server name reported to clients.
        version: Server version reported to clients.
        tools: Tools to expose.
        prompts: Prompts to expose.
        instructions: Optional guidance for the model on using this server.
        cache_ttl_ms: Freshness hint, in milliseconds, sent with `tools/list`,
            `prompts/list`, and `server/discover` results. Tools and prompts are fixed
            when the server is constructed, so this really bounds how long a client may
            miss a redeploy. Use 0 to tell clients never to cache.
        cache_scope: Whether shared caches may serve those results across
            authorization contexts. Defaults to "private" when any tool or prompt is
            scope-restricted (the list then varies by caller) and "public" otherwise.
        allowed_origins: Origins the HTTP transport accepts. Empty (the default)
            disables the check. Set this when the server is reachable from a browser:
            it is the defence against DNS rebinding.

    """

    def __init__(  # noqa: PLR0913
        self,
        name: str,
        version: str,
        tools: tuple[Tool, ...] = (),
        prompts: tuple[Prompt, ...] = (),
        instructions: str | None = None,
        cache_ttl_ms: int = DEFAULT_CACHE_TTL_MS,
        cache_scope: CacheScope | None = None,
        allowed_origins: tuple[str, ...] = (),
    ) -> None:
        _ensure_unique_names("tool", tuple(_tool.name for _tool in tools))
        _ensure_unique_names("prompt", tuple(_prompt.name for _prompt in prompts))
        if cache_ttl_ms < 0:
            msg = "cache_ttl_ms must be greater than or equal to 0"
            raise ValueError(msg)
        self._version = version
        self._name = name
        self._tools = tools
        self._prompts = prompts
        self._instructions = instructions
        self._cache_ttl_ms = cache_ttl_ms
        self._cache_scope: CacheScope = cache_scope or self._derive_cache_scope()
        self._allowed_origins = allowed_origins
        self._http_transport = HTTPTransport(self)
        self._stdio_transport = StdioTransport(self)

    def _derive_cache_scope(self) -> CacheScope:
        is_scoped = any(_tool.scopes for _tool in self._tools) or any(
            _prompt.scopes for _prompt in self._prompts
        )
        return "private" if is_scoped else "public"

    async def app(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._http_transport.handle_request(scope, receive, send)

    async def serve_stdio(self, request_headers: dict[str, str] | None = None) -> None:
        await self._stdio_transport.start(request_headers)

    @property
    def version(self) -> str:
        return self._version

    @property
    def name(self) -> str:
        return self._name

    @property
    def instructions(self) -> str | None:
        return self._instructions

    @property
    def cache_ttl_ms(self) -> int:
        return self._cache_ttl_ms

    @property
    def cache_scope(self) -> CacheScope:
        return self._cache_scope

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return self._allowed_origins

    @property
    def capabilities(self) -> ServerCapabilities:
        capability = Capability(list_changed=False)
        return ServerCapabilities(
            prompts=capability if self._prompts else None,
            tools=capability if self._tools else None,
        )

    def get_tool_input_schema(self, tool_name: str) -> dict | None:
        return next(
            (_tool.input_schema for _tool in self._tools if _tool.name == tool_name),
            None,
        )

    def list_tools(self, request: Request) -> tuple[dict, ...]:
        return tuple(
            _tool.generate_json_schema()
            for _tool in self._tools
            if _check_scope(request, _tool.scopes)
        )

    async def call_tool(
        self,
        tool_name: str,
        args: dict,
        request: Request,
    ) -> BaseModel:
        try:
            tool = next(_tool for _tool in self._tools if _tool.name == tool_name)
        except StopIteration as e:
            raise ToolNotFoundError(tool_name) from e
        if not _check_scope(request, tool.scopes):
            raise InsufficientScopeError(tool.scopes)

        return await tool.invoke(args, request)

    def list_prompts(self, request: Request) -> PromptListResult:
        return PromptListResult(
            prompts=tuple(
                _prompt.to_prompt_protocol_object()
                for _prompt in self._prompts
                if _check_scope(request, _prompt.scopes)
            ),
            next_cursor=None,
        )

    async def get_prompt(
        self,
        prompt_name: str,
        arguments: dict,
        request: Request,
    ) -> PromptGetResult:
        try:
            _prompt = next(_prompt for _prompt in self._prompts if _prompt.name == prompt_name)
        except StopIteration as e:
            raise PromptNotFoundError(prompt_name) from e
        if not _check_scope(request, _prompt.scopes):
            raise InsufficientScopeError(_prompt.scopes)

        result = await _prompt.invoke(arguments, request)
        return PromptGetResult(
            description=_prompt.description,
            messages=result,
        )
