import logging
from http import HTTPStatus
from typing import Any

from pydantic import BaseModel, ValidationError
from starlette.requests import Request

from http_mcp._json_rcp_types.errors import Error, ErrorCode
from http_mcp._json_rcp_types.messages import (
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
)
from http_mcp._mcp_types.content import TextContent
from http_mcp._mcp_types.discover import DiscoverResponse, DiscoverResult
from http_mcp._mcp_types.messages import (
    InitializationRequest,
    InitializeResponse,
    InitializeResponseResult,
    ServerInfo,
)
from http_mcp._mcp_types.meta import (
    META_PROTOCOL_VERSION,
    Implementation,
    RequestMeta,
    ResultMeta,
)
from http_mcp._mcp_types.prompts import (
    PromptGetRequest,
    PromptGetResult,
    PromptsGetResponse,
    PromptsListResponse,
)
from http_mcp._mcp_types.results import CacheableResult, Result
from http_mcp._mcp_types.tools import (
    ToolsCallRequest,
    ToolsCallResponse,
    ToolsCallResult,
    ToolsListRequest,
    ToolsListResponse,
    ToolsListResult,
)
from http_mcp._mcp_types.versions import (
    LEGACY_PROTOCOL_VERSIONS,
    MODERN_PROTOCOL_VERSIONS,
    SUPPORTED_PROTOCOL_VERSIONS,
)
from http_mcp.exceptions import (
    PromptInvocationError,
    ProtocolError,
    ServerError,
    ToolNotFoundError,
)
from http_mcp.server_interface import ServerInterface
from http_mcp.types.utils import sanitize_validation_errors

LOGGER = logging.getLogger(__name__)

TOOLS_CHUNK_SIZE = 100

PROTOCOL_VERSION_HEADER = "mcp-protocol-version"


class _PingResult(BaseModel):
    pass


def request_meta(params: object) -> dict[str, Any]:
    """Return the ``_meta`` block of a request's params, or an empty mapping."""
    if isinstance(params, dict):
        meta = params.get("_meta")
        if isinstance(meta, dict):
            return meta
    return {}


class BaseTransport:
    """Dispatch shared by the HTTP and STDIO transports.

    The server is dual-era. Revision ``2026-07-28`` and later are *modern*: stateless,
    with the protocol version and client capabilities restated in every request's
    ``_meta``. Revisions ``2025-11-25`` and earlier are *legacy*: they open with an
    ``initialize`` handshake. Each request is routed to one era or the other; see
    :meth:`is_modern_request`.
    """

    legacy_versions = LEGACY_PROTOCOL_VERSIONS
    modern_versions = MODERN_PROTOCOL_VERSIONS
    supported_versions = SUPPORTED_PROTOCOL_VERSIONS
    supported_methods = (
        "initialize",
        "ping",
        "server/discover",
        "tools/list",
        "tools/call",
        "prompts/list",
        "prompts/get",
    )
    modern_methods = (
        "server/discover",
        "tools/list",
        "tools/call",
        "prompts/list",
        "prompts/get",
    )

    def __init__(self, server: ServerInterface) -> None:
        self._server = server

    # ------------------------------------------------------------------
    # Era selection
    # ------------------------------------------------------------------

    def is_modern_request(self, method: str, params: object, header_version: str | None) -> bool:
        """Decide whether a request is served under the modern, stateless rules.

        ``server/discover`` exists only in the modern era, and a ``_meta`` protocol
        version is a key no legacy revision defines, so either one settles it. The
        header alone is enough for a modern client whose body is malformed: routing it
        here is what surfaces the missing ``_meta`` as an error rather than silently
        serving it under legacy semantics.
        """
        if method == "server/discover":
            return True
        if META_PROTOCOL_VERSION in request_meta(params):
            return True
        return header_version in self.modern_versions

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def _process_request(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> tuple[JSONRPCMessage, HTTPStatus]:
        header_version = request.headers.get(PROTOCOL_VERSION_HEADER)
        if self.is_modern_request(message.method, message.params, header_version):
            return await self._process_modern_request(message, request)
        return await self._process_legacy_request(message, request)

    async def _process_modern_request(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> tuple[JSONRPCMessage, HTTPStatus]:
        meta = self._validate_request_meta(message)
        if isinstance(meta, JSONRPCError):
            return meta, HTTPStatus.BAD_REQUEST

        if message.method == "server/discover":
            return self._handle_discover(message), HTTPStatus.OK

        response: JSONRPCMessage
        if message.method.startswith("tools/"):
            response = await self._process_tools_request(message, request)
        elif message.method.startswith("prompts/"):
            response = await self._process_prompts_request(message, request)
        else:
            # `initialize`, `ping`, and the notification methods were removed by this
            # revision; on HTTP an unknown method is a 404, not a 400.
            return self._method_not_found(message), HTTPStatus.NOT_FOUND

        self._annotate_response(response)
        return response, HTTPStatus.OK

    async def _process_legacy_request(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> tuple[JSONRPCMessage, HTTPStatus]:
        if message.method == "ping":
            ping_response = JSONRPCResponse(jsonrpc="2.0", id=message.id, result=_PingResult())
            return ping_response, HTTPStatus.OK
        if message.method == "initialize":
            return self._handle_initialization(message)
        if message.method.startswith("tools/"):
            return await self._process_tools_request(message, request), HTTPStatus.OK
        if message.method.startswith("prompts/"):
            return await self._process_prompts_request(message, request), HTTPStatus.OK

        # Remaining validated methods (e.g. notification methods sent with an id)
        # are not callable request methods.
        return self._method_not_found(message), HTTPStatus.BAD_REQUEST

    def _method_not_found(self, message: JSONRPCRequest) -> JSONRPCError:
        return JSONRPCError(
            jsonrpc="2.0",
            id=message.id,
            error=Error(
                code=ErrorCode.METHOD_NOT_FOUND,
                description=f"Method not supported: {message.method}",
            ),
        )

    # ------------------------------------------------------------------
    # Modern request metadata and results
    # ------------------------------------------------------------------

    def _validate_request_meta(self, message: JSONRPCRequest) -> RequestMeta | JSONRPCError:
        """Validate the ``_meta`` every modern request must carry."""
        try:
            meta = RequestMeta.model_validate(request_meta(message.params))
        except ValidationError as e:
            LOGGER.warning("Request _meta validation error for %s", message.method)
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
                    code=ErrorCode.INVALID_PARAMS,
                    description=f"Invalid request _meta: {sanitize_validation_errors(e)}",
                ),
            )

        if meta.protocol_version not in self.modern_versions:
            LOGGER.error("Unsupported protocol version: %s", meta.protocol_version)
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
                    code=ErrorCode.UNSUPPORTED_PROTOCOL_VERSION,
                    description="Unsupported protocol version",
                    data={
                        "supported": list(self.supported_versions),
                        "requested": meta.protocol_version,
                    },
                ),
            )
        return meta

    def _handle_discover(self, message: JSONRPCRequest) -> DiscoverResponse:
        return DiscoverResponse(
            jsonrpc="2.0",
            id=message.id,
            result=self._annotate_result(
                DiscoverResult(
                    supported_versions=self.supported_versions,
                    capabilities=self._server.capabilities,
                    instructions=self._server.instructions,
                ),
            ),
        )

    def _annotate_response(self, response: JSONRPCMessage) -> None:
        """Attach the modern result fields, if this response carries a result."""
        result = getattr(response, "result", None)
        if isinstance(result, Result):
            self._annotate_result(result)

    def _annotate_result[T: Result](self, result: T) -> T:
        result.result_type = "complete"
        result.meta = ResultMeta(
            server_info=Implementation(name=self._server.name, version=self._server.version),
        )
        if isinstance(result, CacheableResult):
            result.ttl_ms = self._server.cache_ttl_ms
            result.cache_scope = self._server.cache_scope
        return result

    # ------------------------------------------------------------------
    # Legacy initialization
    # ------------------------------------------------------------------

    def _handle_initialization(
        self,
        message: JSONRPCRequest,
    ) -> tuple[InitializeResponse | JSONRPCError, HTTPStatus]:
        try:
            message = InitializationRequest.model_validate(message.model_dump())
        except ValidationError as e:
            LOGGER.exception("Initialization validation error")
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
                    code=ErrorCode.INVALID_PARAMS,
                    description=sanitize_validation_errors(e),
                ),
            ), HTTPStatus.BAD_REQUEST
        protocol_version = message.params.protocol_version
        status_code = HTTPStatus.OK
        response: InitializeResponse | JSONRPCError

        if protocol_version in self.legacy_versions:
            response = InitializeResponse(
                jsonrpc="2.0",
                id=message.id,
                result=InitializeResponseResult(
                    protocol_version=protocol_version,
                    capabilities=self._server.capabilities,
                    instructions=self._server.instructions,
                    server_info=ServerInfo(name=self._server.name, version=self._server.version),
                ),
            )
        else:
            LOGGER.error(
                "Unsupported protocol version: %s",
                protocol_version,
                extra={
                    "extra": {
                        "initialization_request": message.model_dump(mode="json", by_alias=True),
                    },
                },
            )
            status_code = HTTPStatus.BAD_REQUEST
            response = JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
                    code=ErrorCode.INVALID_PARAMS,
                    description="Unsupported protocol version",
                    data={
                        # `initialize` exists only in the legacy era, so a legacy client
                        # can act only on the versions that still offer the handshake.
                        "supported": list(self.legacy_versions),
                        "requested": protocol_version,
                    },
                ),
            )
        return response, status_code

    # ------------------------------------------------------------------
    # Features
    # ------------------------------------------------------------------

    async def _process_prompts_request(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> PromptsListResponse | JSONRPCError | PromptsGetResponse:
        if message.method == "prompts/list":
            result = self._server.list_prompts(request)
            return PromptsListResponse(
                jsonrpc="2.0",
                id=message.id,
                result=result,
            )

        try:
            validated_message = PromptGetRequest.model_validate(message.model_dump())
        except ValidationError as e:
            LOGGER.exception("Prompt get validation error")
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
                    code=ErrorCode.INVALID_PARAMS,
                    description=sanitize_validation_errors(e),
                ),
            )

        try:
            prompt_result = await self._server.get_prompt(
                validated_message.params.name,
                validated_message.params.arguments,
                request,
            )
        except PromptInvocationError as e:
            return PromptsGetResponse(
                jsonrpc="2.0",
                id=message.id,
                result=PromptGetResult(
                    description=e.message,
                    messages=(),
                ),
            )
        except (ProtocolError, ServerError) as e:
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
                    code=e.error.code,
                    description=e.message,
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
            try:
                validated_message = ToolsListRequest.model_validate(message.model_dump())
            except ValidationError as e:
                LOGGER.exception("Tools list validation error")
                return JSONRPCError(
                    jsonrpc="2.0",
                    id=message.id,
                    error=Error(
                        code=ErrorCode.INVALID_PARAMS,
                        description=sanitize_validation_errors(e),
                    ),
                )

            all_tools = self._server.list_tools(request)
            sorted_tools = sorted(all_tools, key=lambda x: x["name"])
            total_tools = len(sorted_tools)

            cursor = validated_message.params.cursor if validated_message.params else 0
            start_index = max(0, min(cursor or 0, total_tools))
            end_index = min(start_index + TOOLS_CHUNK_SIZE, total_tools)
            tools = sorted_tools[start_index:end_index]

            # Calculate next cursor if there are more items
            next_cursor: str | None = None
            if end_index < total_tools:
                next_cursor = str(end_index)

            return ToolsListResponse(
                jsonrpc="2.0",
                id=message.id,
                result=ToolsListResult(
                    tools=tuple(tools),
                    next_cursor=next_cursor,
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
            LOGGER.exception("Tool call validation error")
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
                    code=ErrorCode.INVALID_PARAMS,
                    description=sanitize_validation_errors(e),
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
        except (ProtocolError, ToolNotFoundError) as e:
            return JSONRPCError(
                jsonrpc="2.0",
                id=message.id,
                error=Error(
                    code=e.error.code,
                    description=e.message,
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
