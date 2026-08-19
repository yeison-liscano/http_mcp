import json
import logging
from http import HTTPStatus
from typing import Any

from pydantic import ValidationError
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from http_mcp._json_rcp_types.errors import Error, ErrorCode
from http_mcp._json_rcp_types.messages import (
    JSONRPCError,
    JSONRPCRequest,
)
from http_mcp._mcp_types.headers import (
    HEADER_PARAM_PREFIX,
    MISSING,
    collect_header_params,
    decode_header_value,
    extract_argument,
    is_valid_header_value,
    values_match,
)
from http_mcp._mcp_types.meta import META_PROTOCOL_VERSION
from http_mcp._transport_base import PROTOCOL_VERSION_HEADER, BaseTransport, request_meta
from http_mcp._transport_types import ErrorResponseInfo
from http_mcp.exceptions import InsufficientScopeError
from http_mcp.server_interface import ServerInterface

LOGGER = logging.getLogger(__name__)
MAXIMUM_MESSAGE_SIZE = 4 * 1024 * 1024  # 4MB
_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"cache-control", b"no-store"),
]

_METHOD_HEADER = "mcp-method"
_NAME_HEADER = "mcp-name"
# Methods whose subject is mirrored into `Mcp-Name`.
_NAMED_METHODS = ("tools/call", "prompts/get")
_MAX_ECHOED_VALUE = 100


def _echo(value: object) -> str:
    """Render an untrusted header or body value for an error message."""
    return repr(str(value)[:_MAX_ECHOED_VALUE])


def _validate_version_header(headers: Headers, params: dict[str, Any]) -> str | None:
    header_version = headers.get(PROTOCOL_VERSION_HEADER)
    if header_version is None:
        return "MCP-Protocol-Version header is required"
    declared_version = request_meta(params).get(META_PROTOCOL_VERSION)
    if declared_version is not None and header_version != declared_version:
        return (
            f"MCP-Protocol-Version header value {_echo(header_version)} does not match "
            f"body value {_echo(declared_version)}"
        )
    return None


def _validate_method_header(headers: Headers, method: object) -> str | None:
    header_method = headers.get(_METHOD_HEADER)
    if header_method is None:
        return "Mcp-Method header is required"
    if header_method != method:
        return (
            f"Mcp-Method header value {_echo(header_method)} does not match "
            f"body value {_echo(method)}"
        )
    return None


def _validate_name_header(headers: Headers, method: str, params: dict[str, Any]) -> str | None:
    raw_value = headers.get(_NAME_HEADER)
    if raw_value is None:
        return f"Mcp-Name header is required for {method} requests"
    decoded = _decode(raw_value)
    if decoded is None:
        return "Mcp-Name header value is not a valid header value"
    body_name = params.get("name")
    if decoded != body_name:
        return (
            f"Mcp-Name header value {_echo(decoded)} does not match "
            f"body value {_echo(body_name)}"
        )
    return None


def _validate_param_header(
    raw_value: str | None,
    header_name: str,
    body_value: object,
) -> str | None:
    label = f"Mcp-Param-{header_name}"
    if body_value is MISSING or body_value is None:
        if raw_value is not None:
            return f"{label} header was sent but the argument has no value in the body"
        return None
    if raw_value is None:
        return f"{label} header is required because the argument is present in the body"
    decoded = _decode(raw_value)
    if decoded is None:
        return f"{label} header value is not a valid header value"
    if not values_match(decoded, body_value):
        return (
            f"{label} header value {_echo(decoded)} does not match "
            f"body value {_echo(body_value)}"
        )
    return None


def _decode(raw_value: str) -> str | None:
    """Return the usable header value, or None if it is malformed."""
    if not is_valid_header_value(raw_value):
        return None
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
        """Guard against DNS rebinding; disabled while no allowlist is configured."""
        if not self._server.allowed_origins or origin is None:
            return True
        return origin in self._server.allowed_origins

    async def _handle_post_request(self, request: Request, send: Send) -> None:
        body = await request.body()
        if len(body) > MAXIMUM_MESSAGE_SIZE:
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

        try:
            raw_message = json.loads(body)
        except json.JSONDecodeError:
            await self._send_error_response(
                send,
                ErrorResponseInfo(
                    protocol_code=ErrorCode.INVALID_PARAMS,
                    http_status_code=HTTPStatus.BAD_REQUEST,
                    message="Parse error: Invalid body",
                ),
            )
            return

        await self._handle_raw_message(raw_message, send, request)

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
            return None

        method = raw_message.get("method")
        is_notification = (
            isinstance(method, str)
            and method.startswith("notifications/")
            and raw_message.get("id") is None
        )
        if is_notification:
            await send(
                {
                    "type": "http.response.start",
                    "status": HTTPStatus.ACCEPTED.value,
                    "headers": [*_SECURITY_HEADERS],
                },
            )

            await send(
                {
                    "type": "http.response.body",
                    "body": b"",
                    "more_body": False,
                },
            )
            return None

        is_modern = self.is_modern_request(
            method if isinstance(method, str) else "",
            raw_message.get("params"),
            request.headers.get(PROTOCOL_VERSION_HEADER),
        )
        if is_modern:
            mismatch = self._validate_request_headers(raw_message, request)
            if mismatch is not None:
                LOGGER.error("Header validation failed: %s", mismatch)
                await self._send_error_response(
                    send,
                    ErrorResponseInfo(
                        message_id=raw_message.get("id"),
                        protocol_code=ErrorCode.HEADER_MISMATCH,
                        http_status_code=HTTPStatus.BAD_REQUEST,
                        message=f"Header mismatch: {mismatch}",
                    ),
                )
                return None

        try:
            request_message = JSONRPCRequest.model_validate(raw_message)
        except ValidationError:
            LOGGER.exception("Error validating message")
            is_invalid_method = raw_message.get("method", "") not in self.supported_methods
            await self._send_error_response(
                send,
                ErrorResponseInfo(
                    message_id=raw_message.get("id"),
                    protocol_code=(
                        ErrorCode.METHOD_NOT_FOUND
                        if is_invalid_method
                        else ErrorCode.INVALID_PARAMS
                    ),
                    http_status_code=(
                        HTTPStatus.NOT_FOUND
                        if is_invalid_method and is_modern
                        else HTTPStatus.BAD_REQUEST
                    ),
                    message="Error validating message request",
                ),
            )
            return None
        else:
            return await self._process_messages(request_message, send, request)

    # ------------------------------------------------------------------
    # Request metadata headers
    # ------------------------------------------------------------------

    def _validate_request_headers(self, raw_message: dict, request: Request) -> str | None:
        """Check the mirrored headers against the body.

        A load balancer may route on the header while the server acts on the body, so
        the two disagreeing is a security problem, not a cosmetic one. Returns a
        description of the first disagreement, or None when they all agree.
        """
        headers = request.headers
        method = raw_message.get("method")
        raw_params = raw_message.get("params")
        params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}

        mismatch = _validate_version_header(headers, params) or _validate_method_header(
            headers,
            method,
        )
        if mismatch is not None:
            return mismatch

        if method in _NAMED_METHODS:
            mismatch = _validate_name_header(headers, str(method), params)
            if mismatch is not None:
                return mismatch

        if method == "tools/call":
            return self._validate_param_headers(headers, params)
        return None

    def _validate_param_headers(self, headers: Headers, params: dict[str, Any]) -> str | None:
        """Validate the `Mcp-Param-*` headers a tool's `x-mcp-header` annotations require.

        Headers that no annotation claims are ignored, as intermediaries are expected to
        forward unrecognised ones untouched.
        """
        tool_name = params.get("name")
        if not isinstance(tool_name, str):
            return None
        schema = self._server.get_tool_input_schema(tool_name)
        if schema is None:
            # Unknown tool; the dispatcher reports it as invalid params.
            return None
        annotated = collect_header_params(schema)
        if not annotated:
            return None

        raw_arguments = params.get("arguments")
        arguments: dict[str, Any] = raw_arguments if isinstance(raw_arguments, dict) else {}

        for header_name, path in annotated.items():
            mismatch = _validate_param_header(
                headers.get(f"{HEADER_PARAM_PREFIX}{header_name}"),
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
            response, status_code = await self._process_request(message, request)
        except InsufficientScopeError:
            await self._send_forbidden_response(send)
            return
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
                "body": response.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"),
                "more_body": False,
            },
        )

    async def _send_forbidden_response(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": HTTPStatus.FORBIDDEN.value,
                "headers": [
                    (b"content-type", b"application/json"),
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
