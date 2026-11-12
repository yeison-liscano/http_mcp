import logging
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Literal, assert_never

from pydantic import BaseModel, StrictInt, StrictStr
from starlette.requests import Request

from http_mcp._json_rcp_types.errors import Error, ErrorCode
from http_mcp._json_rcp_types.messages import (
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCRequestEnvelope,
)
from http_mcp._mcp_types.content import TextContent
from http_mcp._mcp_types.discover import DiscoverResponse, DiscoverResult
from http_mcp._mcp_types.elicitation import (
    InputRequired,
    RetryRequired,
    supported_elicitation_modes,
)
from http_mcp._mcp_types.meta import Implementation, RequestMeta, ResultMeta
from http_mcp._mcp_types.mrtr import (
    InputRequiredResponse,
    InputRequiredResult,
    RetryRequiredResult,
)
from http_mcp._mcp_types.prompts import (
    PromptGetRequest,
    PromptGetResult,
    PromptListRequest,
    PromptListResult,
    PromptMessage,
    PromptsGetResponse,
    PromptsListResponse,
    RenderedPrompt,
)
from http_mcp._mcp_types.tools import (
    ToolsCallFailure,
    ToolsCallRequest,
    ToolsCallResponse,
    ToolsCallStructuredFailure,
    ToolsCallSuccess,
    ToolsListRequest,
    ToolsListResponse,
    ToolsListResult,
)
from http_mcp._mcp_types.versions import SUPPORTED_PROTOCOL_VERSIONS
from http_mcp._parsing import InvalidModel, Parsed, parse_model
from http_mcp.failures import (
    InsufficientScope,
    InvalidArguments,
    PromptInvocationFailed,
    PromptNotFound,
    PromptServerFailure,
    StructuredToolInvocationFailed,
    ToolInvocationFailed,
    ToolNotFound,
)
from http_mcp.server_interface import PromptGetOutcome, ServerInterface, ToolCallOutcome
from http_mcp.types.continuation import (
    INVOCATION_CONTEXT_KEY,
    InvalidContinuationState,
    InvalidInputResponse,
    InvocationContext,
)
from http_mcp.types.models import ErrorMessage

LOGGER = logging.getLogger(__name__)

TOOLS_CHUNK_SIZE = 100

PROTOCOL_VERSION_HEADER = "mcp-protocol-version"


@dataclass(frozen=True)
class Dispatched:
    """A request that produced a response for the transport to send."""

    response: JSONRPCMessage
    status: HTTPStatus
    type: Literal["dispatched"] = "dispatched"


def error_response(
    message_id: int | str | None,
    code: ErrorCode,
    description: str,
) -> JSONRPCError:
    return JSONRPCError(
        jsonrpc="2.0",
        id=message_id,
        error=Error(code=code, description=description),
    )


def _with_ok_status(response: JSONRPCMessage | InsufficientScope) -> Dispatched | InsufficientScope:
    match response:
        case InsufficientScope():
            return response
        case JSONRPCError(error=Error(code=ErrorCode.MISSING_REQUIRED_CLIENT_CAPABILITY)):
            return Dispatched(response, HTTPStatus.BAD_REQUEST)
        case JSONRPCMessage():
            return Dispatched(response, HTTPStatus.OK)
        case _ as unreachable:
            assert_never(unreachable)


class _RequestId(BaseModel):
    id: StrictInt | StrictStr | None = None


def request_id(raw_message: object) -> int | str | None:
    """Return the id to echo in an error, or None when it is not a valid JSON-RPC id.

    An error about a request that failed validation should still carry that request's
    id when it has a usable one, or the client cannot tell which request it answers.
    """
    match parse_model(_RequestId, raw_message):
        case Parsed(value=parsed):
            return parsed.id
        case InvalidModel():
            return None
        case _ as unreachable:
            assert_never(unreachable)


def request_meta(params: object) -> dict[str, Any]:
    """Return the ``_meta`` block of a request's params, or an empty mapping."""
    if isinstance(params, dict):
        meta = params.get("_meta")
        if isinstance(meta, dict):
            return meta
    return {}


class BaseTransport:
    """Dispatch shared by the HTTP and STDIO transports.

    The server implements one protocol revision, ``2026-07-28``, which is stateless:
    there is no ``initialize`` handshake and no session, so every request restates the
    protocol version and the client's capabilities in its ``_meta``. There is exactly
    one dispatch path, and every request travels it — a request cannot select weaker
    handling by declaring an older revision.
    """

    supported_versions = SUPPORTED_PROTOCOL_VERSIONS
    supported_methods = (
        "server/discover",
        "tools/list",
        "tools/call",
        "prompts/list",
        "prompts/get",
    )

    def __init__(self, server: ServerInterface) -> None:
        self._server = server

    def _parse_request(
        self,
        raw_message: object,
    ) -> JSONRPCRequest | JSONRPCNotification | JSONRPCError:
        if isinstance(raw_message, dict) and "id" not in raw_message:
            match parse_model(JSONRPCNotification, raw_message):
                case Parsed(value=notification):
                    return notification
                case InvalidModel(description=description):
                    return error_response(None, ErrorCode.INVALID_REQUEST, description)
                case _ as invalid_notification:
                    assert_never(invalid_notification)

        match parse_model(JSONRPCRequestEnvelope, raw_message):
            case InvalidModel(description=description):
                return error_response(
                    request_id(raw_message),
                    ErrorCode.INVALID_REQUEST,
                    description,
                )
            case Parsed(value=envelope):
                if envelope.method not in self.supported_methods:
                    return error_response(
                        envelope.id,
                        ErrorCode.METHOD_NOT_FOUND,
                        "Method not supported",
                    )
                match parse_model(JSONRPCRequest, raw_message):
                    case Parsed(value=message):
                        return message
                    case InvalidModel(description=description):
                        return error_response(
                            request_id(raw_message),
                            ErrorCode.INVALID_PARAMS,
                            description,
                        )
                    case _ as invalid_request:
                        assert_never(invalid_request)
            case _ as unreachable:
                assert_never(unreachable)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def _process_request(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> Dispatched | InsufficientScope:
        match self._validate_request_meta(message):
            case JSONRPCError() as error:
                return Dispatched(error, HTTPStatus.BAD_REQUEST)
            case RequestMeta():
                return await self._dispatch(message, request)
            case _ as unreachable:
                assert_never(unreachable)

    async def _dispatch(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> Dispatched | InsufficientScope:
        if not self._method_is_advertised(message):
            return Dispatched(
                error_response(message.id, ErrorCode.METHOD_NOT_FOUND, "Method not supported"),
                HTTPStatus.NOT_FOUND,
            )
        match message.method:
            case "server/discover":
                return Dispatched(self._handle_discover(message), HTTPStatus.OK)
            case "tools/list":
                return Dispatched(self._list_tools(message, request), HTTPStatus.OK)
            case "tools/call":
                return _with_ok_status(await self._call_tool(message, request))
            case "prompts/list":
                return Dispatched(self._list_prompts(message, request), HTTPStatus.OK)
            case "prompts/get":
                return _with_ok_status(await self._get_prompt(message, request))
            case _ as unreachable:
                assert_never(unreachable)

    def _method_is_advertised(self, message: JSONRPCRequest) -> bool:
        match message.method:
            case "server/discover":
                return True
            case "tools/list" | "tools/call":
                return self._server.capabilities.tools is not None
            case "prompts/list" | "prompts/get":
                return self._server.capabilities.prompts is not None
            case _ as unreachable:
                assert_never(unreachable)

    # ------------------------------------------------------------------
    # Request metadata and results
    # ------------------------------------------------------------------

    def _validate_request_meta(self, message: JSONRPCRequest) -> RequestMeta | JSONRPCError:
        """Validate the ``_meta`` every request must carry."""
        match parse_model(RequestMeta, request_meta(message.params)):
            case InvalidModel(description=description):
                LOGGER.warning("Request _meta validation error for %s", message.method)
                return error_response(
                    message.id,
                    ErrorCode.INVALID_PARAMS,
                    f"Invalid request _meta: {description}",
                )
            case Parsed(value=meta) if meta.protocol_version in self.supported_versions:
                return meta
            case Parsed(value=meta):
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
            case _ as unreachable:
                assert_never(unreachable)

    def _result_meta(self) -> ResultMeta:
        return ResultMeta(
            server_info=Implementation(name=self._server.name, version=self._server.version),
        )

    def _handle_discover(self, message: JSONRPCRequest) -> DiscoverResponse:
        return DiscoverResponse(
            jsonrpc="2.0",
            id=message.id,
            result=DiscoverResult(
                meta=self._result_meta(),
                ttl_ms=self._server.cache_ttl_ms,
                cache_scope=self._server.cache_scope,
                supported_versions=self.supported_versions,
                capabilities=self._server.capabilities,
                instructions=self._server.instructions,
            ),
        )

    # ------------------------------------------------------------------
    # Features
    # ------------------------------------------------------------------

    def _list_prompts(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> PromptsListResponse | JSONRPCError:
        match parse_model(PromptListRequest, message.model_dump()):
            case InvalidModel(description=description):
                return error_response(message.id, ErrorCode.INVALID_PARAMS, description)
            case Parsed(value=validated):
                if validated.params is not None and validated.params.cursor not in (None, 0):
                    # Prompts are returned in one page, so no nonzero continuation
                    # cursor has been issued by this server.
                    return error_response(message.id, ErrorCode.INVALID_PARAMS, "Invalid cursor")
            case _ as unreachable:
                assert_never(unreachable)
        return PromptsListResponse(
            jsonrpc="2.0",
            id=message.id,
            result=PromptListResult(
                meta=self._result_meta(),
                ttl_ms=self._server.cache_ttl_ms,
                cache_scope=self._server.cache_scope,
                prompts=self._server.list_prompts(request),
                next_cursor=None,
            ),
        )

    async def _get_prompt(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> PromptsGetResponse | InputRequiredResponse | JSONRPCError | InsufficientScope:
        match parse_model(PromptGetRequest, message.model_dump()):
            case InvalidModel(description=description):
                LOGGER.error("Prompt get validation error")
                return error_response(message.id, ErrorCode.INVALID_PARAMS, description)
            case Parsed(value=validated):
                request.scope[INVOCATION_CONTEXT_KEY] = InvocationContext(
                    method="prompts/get",
                    name=validated.params.name,
                    arguments=validated.params.arguments,
                    input_responses=validated.params.input_responses,
                    request_state=validated.params.request_state,
                    elicitation_modes=supported_elicitation_modes(
                        request_meta(message.params)["io.modelcontextprotocol/clientCapabilities"].get(
                            "elicitation",
                        ),
                    ),
                )
                outcome = await self._server.get_prompt(
                    validated.params.name,
                    validated.params.arguments,
                    request,
                )
                return self._prompt_response(message, outcome)
            case _ as unreachable:
                assert_never(unreachable)

    def _prompt_response(
        self,
        message: JSONRPCRequest,
        outcome: PromptGetOutcome,
    ) -> PromptsGetResponse | InputRequiredResponse | JSONRPCError | InsufficientScope:
        message_id = message.id
        match outcome:
            case InputRequired() | RetryRequired():
                return self._mrtr_response(message, outcome)
            case RenderedPrompt(description=description, messages=messages):
                return self._prompt_result(message_id, description, messages)
            case PromptInvocationFailed(message=failure):
                return self._prompt_result(message_id, failure, ())
            case (
                PromptNotFound()
                | InvalidArguments()
                | InvalidContinuationState()
                | InvalidInputResponse()
            ) as rejected:
                return error_response(message_id, ErrorCode.INVALID_PARAMS, rejected.message)
            case PromptServerFailure(code=code, message=failure):
                return error_response(message_id, code, failure)
            case InsufficientScope():
                return outcome
            case _ as unreachable:
                assert_never(unreachable)

    def _prompt_result(
        self,
        message_id: int | str | None,
        description: str,
        messages: tuple[PromptMessage, ...],
    ) -> PromptsGetResponse:
        return PromptsGetResponse(
            jsonrpc="2.0",
            id=message_id,
            result=PromptGetResult(
                meta=self._result_meta(),
                description=description,
                messages=messages,
            ),
        )

    def _mrtr_response(
        self,
        message: JSONRPCRequest,
        outcome: InputRequired | RetryRequired,
    ) -> InputRequiredResponse | JSONRPCError:
        match outcome:
            case RetryRequired(request_state=state):
                result = RetryRequiredResult(meta=self._result_meta(), request_state=state)
                return InputRequiredResponse(jsonrpc="2.0", id=message.id, result=result)
            case InputRequired(input_requests=requests, request_state=state):
                meta = request_meta(message.params)
                capabilities = meta["io.modelcontextprotocol/clientCapabilities"]
                declared = capabilities.get("elicitation")
                required_modes = {item.params.mode for item in requests.values()}
                if isinstance(declared, dict) and not required_modes.issubset(
                    supported_elicitation_modes(declared),
                ):
                    return error_response(
                        message.id,
                        ErrorCode.INVALID_PARAMS,
                        "Client does not support the requested elicitation mode",
                    )
                if not isinstance(declared, dict):
                    return JSONRPCError(
                        jsonrpc="2.0",
                        id=message.id,
                        error=Error(
                            code=ErrorCode.MISSING_REQUIRED_CLIENT_CAPABILITY,
                            description="Client does not support the required elicitation modes",
                            data={
                                "requiredCapabilities": {
                                    "elicitation": {mode: {} for mode in sorted(required_modes)},
                                },
                            },
                        ),
                    )
                return InputRequiredResponse(
                    jsonrpc="2.0",
                    id=message.id,
                    result=InputRequiredResult(
                        meta=self._result_meta(),
                        input_requests=requests,
                        request_state=state,
                    ),
                )
            case _ as unreachable:
                assert_never(unreachable)

    def _list_tools(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> ToolsListResponse | JSONRPCError:
        match parse_model(ToolsListRequest, message.model_dump()):
            case InvalidModel(description=description):
                LOGGER.error("Tools list validation error")
                return error_response(message.id, ErrorCode.INVALID_PARAMS, description)
            case Parsed(value=validated):
                return self._tools_page(validated, request)
            case _ as unreachable:
                assert_never(unreachable)

    def _tools_page(
        self,
        message: ToolsListRequest,
        request: Request,
    ) -> ToolsListResponse | JSONRPCError:
        all_tools = self._server.list_tools(request)
        sorted_tools = sorted(all_tools, key=lambda x: x["name"])
        total_tools = len(sorted_tools)

        cursor = message.params.cursor if message.params else 0
        start_index = cursor or 0
        if start_index and start_index >= total_tools:
            return error_response(message.id, ErrorCode.INVALID_PARAMS, "Invalid cursor")
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
                meta=self._result_meta(),
                ttl_ms=self._server.cache_ttl_ms,
                cache_scope=self._server.cache_scope,
                tools=tuple(tools),
                next_cursor=next_cursor,
            ),
        )

    async def _call_tool(
        self,
        message: JSONRPCRequest,
        request: Request,
    ) -> ToolsCallResponse | InputRequiredResponse | JSONRPCError | InsufficientScope:
        match parse_model(ToolsCallRequest, message.model_dump()):
            case InvalidModel(description=description):
                LOGGER.error("Tool call validation error")
                return error_response(message.id, ErrorCode.INVALID_PARAMS, description)
            case Parsed(value=validated):
                request.scope[INVOCATION_CONTEXT_KEY] = InvocationContext(
                    method="tools/call",
                    name=validated.params.name,
                    arguments=validated.params.arguments,
                    input_responses=validated.params.input_responses,
                    request_state=validated.params.request_state,
                    elicitation_modes=supported_elicitation_modes(
                        request_meta(message.params)["io.modelcontextprotocol/clientCapabilities"].get(
                            "elicitation",
                        ),
                    ),
                )
                outcome = await self._server.call_tool(
                    validated.params.name,
                    validated.params.arguments,
                    request,
                )
                return self._tool_response(message, outcome)
            case _ as unreachable:
                assert_never(unreachable)

    def _tool_response(
        self,
        message: JSONRPCRequest,
        outcome: ToolCallOutcome,
    ) -> ToolsCallResponse | InputRequiredResponse | JSONRPCError | InsufficientScope:
        message_id = message.id
        match outcome:
            case InputRequired() | RetryRequired():
                return self._mrtr_response(message, outcome)
            case BaseModel() as returned_value:
                return ToolsCallResponse(
                    jsonrpc="2.0",
                    id=message_id,
                    result=ToolsCallSuccess(
                        meta=self._result_meta(),
                        content=(
                            TextContent(
                                type="text",
                                text=returned_value.model_dump_json(by_alias=True),
                            ),
                        ),
                        structured_content=returned_value.model_dump(mode="json", by_alias=True),
                    ),
                )
            case ToolInvocationFailed(message=failure):
                return ToolsCallResponse(
                    jsonrpc="2.0",
                    id=message_id,
                    result=ToolsCallFailure(
                        meta=self._result_meta(),
                        content=(TextContent(type="text", text=failure),),
                    ),
                )
            case StructuredToolInvocationFailed(message=failure):
                data = ErrorMessage(error_message=failure)
                return ToolsCallResponse(
                    jsonrpc="2.0",
                    id=message_id,
                    result=ToolsCallStructuredFailure(
                        meta=self._result_meta(),
                        content=(TextContent(type="text", text=data.model_dump_json()),),
                        structured_content=data.model_dump(mode="json"),
                    ),
                )
            case (
                ToolNotFound()
                | InvalidArguments()
                | InvalidContinuationState()
                | InvalidInputResponse()
            ) as rejected:
                return error_response(message_id, ErrorCode.INVALID_PARAMS, rejected.message)
            case InsufficientScope():
                return outcome
            case _ as unreachable:
                assert_never(unreachable)
