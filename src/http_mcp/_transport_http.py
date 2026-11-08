import logging
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Literal, assert_never
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from http_mcp._json_rcp_types.errors import Error, ErrorCode
from http_mcp._json_rcp_types.messages import (
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
)
from http_mcp._mcp_types.headers import (
    HEADER_PARAM_PREFIX,
    ArgumentAbsent,
    ArgumentPresent,
    DuplicateHeaderParamError,
    MalformedHeaderValue,
    collect_header_params,
    decode_header_value,
    extract_argument,
    is_valid_header_value,
    values_match,
)
from http_mcp._mcp_types.meta import META_PROTOCOL_VERSION
from http_mcp._parsing import InvalidJson, Parsed, parse_json
from http_mcp._transport_base import (
    PROTOCOL_VERSION_HEADER,
    BaseTransport,
    Dispatched,
    request_id,
    request_meta,
)
from http_mcp._transport_types import ErrorResponseInfo
from http_mcp.failures import InsufficientScope
from http_mcp.server_interface import ServerInterface

LOGGER = logging.getLogger(__name__)
MAXIMUM_MESSAGE_SIZE = 4 * 1024 * 1024  # 4MB
_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"cache-control", b"no-store"),
]

_METHOD_HEADER = "mcp-method"
_NAME_HEADER = "mcp-name"
# Every header the body is mirrored into, with the spelling used in error messages.
_MIRRORED_HEADERS: dict[str, str] = {
    PROTOCOL_VERSION_HEADER: "MCP-Protocol-Version",
    _METHOD_HEADER: "Mcp-Method",
    _NAME_HEADER: "Mcp-Name",
}
# Hosts an `Origin` may name when no allowlist is configured.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# RFC 6749 section 3.3 scope-token characters; anything else is left out of the challenge.
_SCOPE_TOKEN = re.compile(r"[\x21\x23-\x5b\x5d-\x7e]+")
# Methods whose subject is mirrored into `Mcp-Name`.
_NAMED_METHODS = ("tools/call", "prompts/get")
_MAX_ECHOED_VALUE = 100


@dataclass(frozen=True)
class HeaderMismatch:
    """A mirrored header disagrees with the body, or is missing or malformed."""

    detail: str
    type: Literal["header_mismatch"] = "header_mismatch"


def _echo(value: object) -> str:
    """Render an untrusted header or body value for an error message."""
    return repr(str(value)[:_MAX_ECHOED_VALUE])


def _find_repeated_header(headers: Headers, names: dict[str, str]) -> HeaderMismatch | None:
    """Refuse a mirrored header that appears more than once.

    `Headers.get` returns the first field line only, while intermediaries commonly join
    repeated lines with ", " (RFC 9110 section 5.3) or keep the last one. A request
    whose first copy matches the body and whose second copy does not would then be
    routed on one value and served on another, which is the desynchronisation the
    mirroring check exists to prevent.
    """
    for name, label in names.items():
        if len(headers.getlist(name)) > 1:
            return HeaderMismatch(f"{label} header must not be repeated")
    return None


def _is_loopback_origin(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and parsed.hostname in _LOOPBACK_HOSTS


def _insufficient_scope_challenge(required_scopes: tuple[str, ...]) -> bytes:
    """Build the RFC 6750 challenge that lets a client step up to the scopes it lacks."""
    scope = " ".join(s for s in required_scopes if _SCOPE_TOKEN.fullmatch(s))
    if not scope:
        return b'Bearer error="insufficient_scope"'
    return f'Bearer error="insufficient_scope", scope="{scope}"'.encode("ascii")


def _validate_version_header(headers: Headers, params: dict[str, Any]) -> HeaderMismatch | None:
    header_version = headers.get(PROTOCOL_VERSION_HEADER)
    if header_version is None:
        return HeaderMismatch("MCP-Protocol-Version header is required")
    declared_version = request_meta(params).get(META_PROTOCOL_VERSION)
    if declared_version is not None and header_version != declared_version:
        return HeaderMismatch(
            f"MCP-Protocol-Version header value {_echo(header_version)} does not match "
            f"body value {_echo(declared_version)}",
        )
    return None


def _validate_method_header(headers: Headers, method: object) -> HeaderMismatch | None:
    header_method = headers.get(_METHOD_HEADER)
    if header_method is None:
        return HeaderMismatch("Mcp-Method header is required")
    if header_method != method:
        return HeaderMismatch(
            f"Mcp-Method header value {_echo(header_method)} does not match "
            f"body value {_echo(method)}",
        )
    return None


def _validate_name_header(
    headers: Headers,
    method: str,
    params: dict[str, Any],
) -> HeaderMismatch | None:
    raw_value = headers.get(_NAME_HEADER)
    if raw_value is None:
        return HeaderMismatch(f"Mcp-Name header is required for {method} requests")
    match _decode(raw_value):
        case MalformedHeaderValue():
            return HeaderMismatch("Mcp-Name header value is not a valid header value")
        case str() as decoded:
            body_name = params.get("name")
            if decoded != body_name:
                return HeaderMismatch(
                    f"Mcp-Name header value {_echo(decoded)} does not match "
                    f"body value {_echo(body_name)}",
                )
            return None
        case _ as unreachable:
            assert_never(unreachable)


def _validate_param_header(
    raw_value: str | None,
    header_name: str,
    argument: ArgumentAbsent | ArgumentPresent,
) -> HeaderMismatch | None:
    label = f"Mcp-Param-{header_name}"
    match argument:
        case ArgumentAbsent() | ArgumentPresent(value=None):
            if raw_value is None:
                return None
            return HeaderMismatch(
                f"{label} header was sent but the argument has no value in the body",
            )
        case ArgumentPresent(value=body_value):
            if raw_value is None:
                return HeaderMismatch(
                    f"{label} header is required because the argument is present in the body",
                )
            match _decode(raw_value):
                case MalformedHeaderValue():
                    return HeaderMismatch(f"{label} header value is not a valid header value")
                case str() as decoded:
                    if values_match(decoded, body_value):
                        return None
                    return HeaderMismatch(
                        f"{label} header value {_echo(decoded)} does not match "
                        f"body value {_echo(body_value)}",
                    )
                case _ as unreachable:
                    assert_never(unreachable)
        case _ as unreachable:
            assert_never(unreachable)


def _decode(raw_value: str) -> str | MalformedHeaderValue:
    """Return the usable header value."""
    if not is_valid_header_value(raw_value):
        return MalformedHeaderValue()
    return decode_header_value(raw_value)


class HTTPTransport(BaseTransport):
    def __init__(self, server: ServerInterface) -> None:
        super().__init__(server)

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)

        if request.method != "POST":
            # GET and DELETE served the standalone SSE stream and session teardown of
            # earlier revisions. Neither exists any more.
            await self._handle_unsupported_request(send)
            return

        if not self._is_allowed_origin(request.headers.get("origin")):
            LOGGER.error("Rejected request from disallowed origin")
            await self._send_error_response(
                send,
                ErrorResponseInfo(
                    protocol_code=ErrorCode.INVALID_REQUEST,
                    http_status_code=HTTPStatus.FORBIDDEN,
                    message="Origin not allowed",
                ),
            )
            return

        content_type = request.headers.get("content-type")
        # Not support for SSE
        if not content_type or content_type.split(";")[0].strip().lower() != "application/json":
            LOGGER.error("Unsupported Media Type: %s", content_type)
            await self._send_error_response(
                send,
                ErrorResponseInfo(
                    protocol_code=ErrorCode.INVALID_PARAMS,
                    http_status_code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    message="Unsupported Media Type: Content-Type must be application/json",
                    headers={"Content-Type": "application/json"},
                ),
            )
            return
        await self._handle_post_request(request, send)

    def _is_allowed_origin(self, origin: str | None) -> bool:
        """Guard against DNS rebinding.

        Without an allowlist only loopback origins are accepted. A page that rebinds its
        own hostname to 127.0.0.1 still sends its own origin, so refusing every origin
        but loopback ones protects a local server that was never configured; a server
        meant for browsers elsewhere names its origins in ``allowed_origins``.

        A missing ``Origin`` is allowed by default: browsers always send one on a POST,
        so absence means a non-browser client, which the rebinding threat model does not
        cover. Servers that only ever expect browser traffic can set ``require_origin``
        to close that gap and make the allowlist mandatory rather than advisory.
        """
        if not self._server.allowed_origins:
            return origin is None or _is_loopback_origin(origin)
        if origin is None:
            return not self._server.require_origin
        return origin in self._server.allowed_origins

    async def _read_body(self, request: Request) -> bytes | None:
        """Read the body, refusing to buffer more than ``MAXIMUM_MESSAGE_SIZE``.

        The cap has to be applied while reading, not after. ``Request.body()`` drains
        the whole stream into memory first, which commits the allocation before the
        limit is consulted and lets an oversized request cost what it asks for rather
        than what the server allows. Returns None when the limit is exceeded.
        """
        declared = request.headers.get("content-length")
        # `isdigit` alone accepts digits such as "²" that `int` then refuses to parse.
        if (
            declared is not None
            and declared.isascii()
            and declared.isdigit()
            and int(declared) > MAXIMUM_MESSAGE_SIZE
        ):
            return None

        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAXIMUM_MESSAGE_SIZE:
                # Stop reading here; the remainder is never buffered.
                return None
            chunks.append(chunk)
        return b"".join(chunks)

    async def _handle_post_request(self, request: Request, send: Send) -> None:
        body = await self._read_body(request)
        if body is None:
            LOGGER.error("Request body too large")
            await self._send_error_response(
                send,
                ErrorResponseInfo(
                    protocol_code=ErrorCode.INVALID_PARAMS,
                    http_status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    message="Request body too large.",
                ),
            )
            return

        match parse_json(body):
            case InvalidJson():
                await self._send_error_response(
                    send,
                    ErrorResponseInfo(
                        protocol_code=ErrorCode.PARSE_ERROR,
                        http_status_code=HTTPStatus.BAD_REQUEST,
                        message="Parse error: Invalid body",
                    ),
                )
            case Parsed(value=raw_message):
                await self._handle_raw_message(raw_message, send, request)
            case _ as unreachable:
                assert_never(unreachable)

    async def _handle_raw_message(
        self,
        raw_message: object,
        send: Send,
        request: Request,
    ) -> None:
        if not isinstance(raw_message, dict):
            LOGGER.error("Invalid request: body is not a JSON object")
            await self._send_error_response(
                send,
                ErrorResponseInfo(
                    protocol_code=ErrorCode.INVALID_REQUEST,
                    http_status_code=HTTPStatus.BAD_REQUEST,
                    message="Invalid Request: body must be a single JSON-RPC request object",
                ),
            )
            return

        parsed = self._parse_request(raw_message)

        # Every request carries the metadata envelope, so every request is checked.
        # There is no second dispatch path a caller could pick to skip this —
        # notifications included, which is why this sits above the 202 below.
        mismatch = self._validate_request_headers(raw_message, request)
        if mismatch is not None:
            LOGGER.error("Header validation failed: %s", mismatch.detail)
            if isinstance(parsed, JSONRPCNotification):
                await self._send_empty_response(send, HTTPStatus.BAD_REQUEST)
                return
            await self._send_error_response(
                send,
                ErrorResponseInfo(
                    message_id=request_id(raw_message),
                    protocol_code=ErrorCode.HEADER_MISMATCH,
                    http_status_code=HTTPStatus.BAD_REQUEST,
                    message=f"Header mismatch: {mismatch.detail}",
                ),
            )
            return

        match parsed:
            case JSONRPCNotification():
                await self._send_empty_response(send, HTTPStatus.ACCEPTED)
            case JSONRPCError() as error:
                LOGGER.error("Error validating message")
                is_invalid_method = error.error.code == ErrorCode.METHOD_NOT_FOUND
                await self._send_error_response(
                    send,
                    ErrorResponseInfo(
                        message_id=request_id(raw_message),
                        protocol_code=error.error.code,
                        http_status_code=(
                            HTTPStatus.NOT_FOUND if is_invalid_method else HTTPStatus.BAD_REQUEST
                        ),
                        message=error.error.message,
                    ),
                )
            case JSONRPCRequest() as request_message:
                await self._process_messages(request_message, send, request)
            case _ as unreachable:
                assert_never(unreachable)

    async def _send_empty_response(self, send: Send, status: HTTPStatus) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status.value,
                "headers": [*_SECURITY_HEADERS],
            },
        )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    # ------------------------------------------------------------------
    # Request metadata headers
    # ------------------------------------------------------------------

    def _validate_request_headers(
        self,
        raw_message: dict,
        request: Request,
    ) -> HeaderMismatch | None:
        """Check the mirrored headers against the body.

        A load balancer may route on the header while the server acts on the body, so
        the two disagreeing is a security problem, not a cosmetic one. Returns the
        first disagreement, or None when they all agree.

        This runs on every request. The check must not be reachable around: a caller
        that could opt out of it could desynchronise an intermediary from the server.
        """
        headers = request.headers
        method = raw_message.get("method")
        raw_params = raw_message.get("params")
        params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}

        mismatch = (
            _find_repeated_header(headers, _MIRRORED_HEADERS)
            or _validate_version_header(headers, params)
            or _validate_method_header(headers, method)
        )
        if mismatch is not None:
            return mismatch

        if method in _NAMED_METHODS:
            mismatch = _validate_name_header(headers, str(method), params)
            if mismatch is not None:
                return mismatch

        if method == "tools/call":
            return self._validate_param_headers(headers, params, request)
        return None

    def _validate_param_headers(
        self,
        headers: Headers,
        params: dict[str, Any],
        request: Request,
    ) -> HeaderMismatch | None:
        """Validate the `Mcp-Param-*` headers a tool's `x-mcp-header` annotations require.

        Headers that no annotation claims are ignored, as intermediaries are expected to
        forward unrecognised ones untouched.

        The schema lookup is scope-aware. This runs ahead of dispatch, so a lookup that
        ignored scopes would answer questions about tools the caller cannot see: the
        mismatch messages below name the annotated arguments, which would disclose part
        of a restricted tool's input schema to a caller `tools/list` hides it from.
        """
        tool_name = params.get("name")
        if not isinstance(tool_name, str):
            return None
        schema = self._server.get_tool_input_schema(tool_name, request)
        if schema is None:
            # Unknown tool, or one this caller may not see. Either way the dispatcher
            # is the only thing that gets to respond about it.
            return None
        try:
            annotated = collect_header_params(schema)
        except DuplicateHeaderParamError:
            # A colliding schema cannot be checked correctly, so refuse the call rather
            # than serve it with one of the two annotations silently unenforced.
            LOGGER.exception("Tool schema declares a duplicate x-mcp-header")
            return HeaderMismatch("tool schema declares a duplicate x-mcp-header annotation")
        if not annotated:
            return None

        raw_arguments = params.get("arguments")
        arguments: dict[str, Any] = raw_arguments if isinstance(raw_arguments, dict) else {}

        for header_name, path in annotated.items():
            field_name = f"{HEADER_PARAM_PREFIX}{header_name}"
            mismatch = _find_repeated_header(
                headers,
                {field_name: f"Mcp-Param-{header_name}"},
            ) or _validate_param_header(
                headers.get(field_name),
                header_name,
                extract_argument(arguments, path),
            )
            if mismatch is not None:
                return mismatch
        return None

    # ------------------------------------------------------------------
    # Responses
    # ------------------------------------------------------------------

    async def _process_messages(
        self,
        message: JSONRPCRequest,
        send: Send,
        request: Request,
    ) -> None:
        try:
            outcome = await self._process_request(message, request)
        except Exception:
            LOGGER.exception("Unexpected error processing request")
            await self._send_error_response(
                send,
                ErrorResponseInfo(
                    message_id=message.id,
                    protocol_code=ErrorCode.INTERNAL_ERROR,
                    http_status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    message="Internal server error",
                ),
            )
            return

        match outcome:
            case InsufficientScope(required_scopes=required_scopes):
                await self._send_forbidden_response(send, required_scopes)
            case Dispatched(response=response, status=status_code):
                await send(
                    {
                        "type": "http.response.start",
                        "status": status_code.value,
                        "headers": [
                            (b"content-type", b"application/json"),
                            *_SECURITY_HEADERS,
                        ],
                    },
                )

                await send(
                    {
                        "type": "http.response.body",
                        "body": response.model_dump_json(by_alias=True, exclude_none=True).encode(
                            "utf-8",
                        ),
                        "more_body": False,
                    },
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def _send_forbidden_response(self, send: Send, required_scopes: tuple[str, ...]) -> None:
        """Answer 403 with a challenge naming the scopes the call needs.

        The scope list is what lets an OAuth client request a token with more scopes
        (step-up authorization). It also tells a caller holding a token which scopes a
        tool it cannot use requires; that is the trade-off step-up makes.
        """
        await send(
            {
                "type": "http.response.start",
                "status": HTTPStatus.FORBIDDEN.value,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", _insufficient_scope_challenge(required_scopes)),
                    *_SECURITY_HEADERS,
                ],
            },
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"error":"insufficient_scope"}',
                "more_body": False,
            },
        )

    async def _handle_unsupported_request(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": HTTPStatus.METHOD_NOT_ALLOWED.value,
                "headers": [
                    (b"allow", b"POST"),
                    (b"content-type", b"text/plain"),
                    *_SECURITY_HEADERS,
                ],
            },
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"Method Not Allowed",
                "more_body": False,
            },
        )

    async def _send_error_response(
        self,
        send: Send,
        error_info: ErrorResponseInfo,
    ) -> None:
        error_response = JSONRPCError(
            jsonrpc="2.0",
            id=error_info.message_id,
            error=Error(
                code=error_info.protocol_code,
                description=error_info.message,
            ),
        )

        response_headers = [(b"content-type", b"application/json"), *_SECURITY_HEADERS]
        if error_info.headers:
            response_headers.extend(
                [(k.lower().encode(), v.encode()) for k, v in error_info.headers.items()],
            )

        await send(
            {
                "type": "http.response.start",
                "status": error_info.http_status_code.value,
                "headers": response_headers,
            },
        )

        await send(
            {
                "type": "http.response.body",
                "body": error_response.model_dump_json(by_alias=True, exclude_none=True).encode(
                    "utf-8",
                ),
                "more_body": False,
            },
        )
