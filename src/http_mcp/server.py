from typing import get_args

from pydantic import BaseModel
from starlette.authentication import has_required_scope
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from http_mcp._mcp_types.capabilities import Capability, ServerCapabilities
from http_mcp._mcp_types.headers import DuplicateHeaderParamError, collect_header_params
from http_mcp._mcp_types.prompts import ProtocolPrompt
from http_mcp._mcp_types.results import CacheScope
from http_mcp._stdio_transport import StdioTransport
from http_mcp._transport_http import HTTPTransport
from http_mcp.failures import InsufficientScope, PromptNotFound, ToolNotFound
from http_mcp.server_interface import PromptGetOutcome, ServerInterface, ToolCallOutcome
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


def _models_in(annotation: object) -> tuple[type[BaseModel], ...]:
    """Return the pydantic models an annotation validates into, such as both of `A | B`."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return (annotation,)
    return tuple(model for arg in get_args(annotation) for model in _models_in(arg))


def _is_read_by_name_only(model: type[BaseModel], path: tuple[str, ...]) -> bool:
    """Report whether validation takes each step of `path` from that key and no other.

    The header check reads the argument at the path the schema advertises. If a field on
    that path also answers to an alias, a request can put one value under the advertised
    key, for the check to compare, and another under the alias, for the tool to receive.
    """
    key, *rest = path
    field = model.model_fields.get(key)
    if field is None or field.validation_alias not in (None, key):
        return False
    return (
        all(_is_read_by_name_only(nested, tuple(rest)) for nested in _models_in(field.annotation))
        if rest
        else True
    )


def _ensure_header_params_are_checkable(tools: tuple[Tool, ...]) -> None:
    """Reject a tool whose `x-mcp-header` annotations the transport cannot enforce.

    Two cases are refused, both at construction rather than per request:

    - One header name declared twice. `collect_header_params` raises rather than letting
      the second annotation overwrite the first, which would leave a property unchecked
      while the server still reported it as validated.
    - An annotated field that the input model also accepts under an alias. The check
      compares the header with the value under the field name while the tool receives
      the value under the alias, so the two could differ.
    """
    for _tool in tools:
        try:
            annotated = collect_header_params(_tool.input_schema)
        except DuplicateHeaderParamError as e:
            msg = f"Tool {_tool.name!r} has an invalid input schema: {e}"
            raise ValueError(msg) from e
        inputs = _tool.inputs
        if not (isinstance(inputs, type) and issubclass(inputs, BaseModel)):
            continue
        aliased = sorted(
            ".".join(path) for path in annotated.values() if not _is_read_by_name_only(inputs, path)
        )
        if aliased:
            msg = (
                f"Tool {_tool.name!r} mirrors {aliased} into Mcp-Param headers, but its "
                "input model also accepts those arguments under an alias. Remove the alias "
                "(alias, validation_alias or alias_generator) from the annotated fields."
            )
            raise ValueError(msg)


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
        allowed_origins: Origins the HTTP transport accepts, the defence against DNS
            rebinding. Empty (the default) accepts only loopback origins
            (`localhost`, `127.0.0.1`, `[::1]`), which suits a local server; set it
            when browsers on any other origin should reach the server.
        require_origin: Whether a request that sends no `Origin` header at all is
            refused when `allowed_origins` is set. Off by default, because browsers
            always send `Origin` on a POST and non-browser clients generally do not.
            Turn it on for a server that should only ever serve browser traffic, which
            makes the allowlist mandatory rather than advisory.

    """

    def __init__(  # noqa: PLR0913
        self,
        name: str,
        version: str,
        tools: tuple[Tool, ...] = (),
        prompts: tuple[Prompt, ...] = (),
        instructions: str | None = None,
        *,
        cache_ttl_ms: int = DEFAULT_CACHE_TTL_MS,
        cache_scope: CacheScope | None = None,
        allowed_origins: tuple[str, ...] = (),
        require_origin: bool = False,
    ) -> None:
        _ensure_unique_names("tool", tuple(_tool.name for _tool in tools))
        _ensure_unique_names("prompt", tuple(_prompt.name for _prompt in prompts))
        _ensure_header_params_are_checkable(tools)
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
        self._require_origin = require_origin
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
    def require_origin(self) -> bool:
        return self._require_origin

    @property
    def capabilities(self) -> ServerCapabilities:
        capability = Capability(list_changed=False)
        return ServerCapabilities(
            prompts=capability if self._prompts else None,
            tools=capability if self._tools else None,
        )

    def get_tool_input_schema(self, tool_name: str, request: Request) -> dict | None:
        return next(
            (
                _tool.input_schema
                for _tool in self._tools
                if _tool.name == tool_name and _check_scope(request, _tool.scopes)
            ),
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
    ) -> ToolCallOutcome:
        tool = next((_tool for _tool in self._tools if _tool.name == tool_name), None)
        if tool is None:
            return ToolNotFound(tool_name)
        if not _check_scope(request, tool.scopes):
            return InsufficientScope(tool.scopes)

        return await tool.invoke(args, request)

    def list_prompts(self, request: Request) -> tuple[ProtocolPrompt, ...]:
        return tuple(
            _prompt.to_prompt_protocol_object()
            for _prompt in self._prompts
            if _check_scope(request, _prompt.scopes)
        )

    async def get_prompt(
        self,
        prompt_name: str,
        arguments: dict,
        request: Request,
    ) -> PromptGetOutcome:
        prompt = next((_prompt for _prompt in self._prompts if _prompt.name == prompt_name), None)
        if prompt is None:
            return PromptNotFound(prompt_name)
        if not _check_scope(request, prompt.scopes):
            return InsufficientScope(prompt.scopes)

        return await prompt.invoke(arguments, request)
