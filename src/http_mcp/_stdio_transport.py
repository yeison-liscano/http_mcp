import asyncio
import logging
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, assert_never

from starlette.requests import Request

from http_mcp._json_rcp_types.errors import ErrorCode
from http_mcp._json_rcp_types.messages import (
    JSONRPCMessage,
    JSONRPCRequest,
)
from http_mcp._parsing import InvalidJson, InvalidModel, Parsed, parse_json, parse_model
from http_mcp._transport_base import BaseTransport, Dispatched, error_response
from http_mcp.failures import InsufficientScope
from http_mcp.server_interface import ServerInterface

if TYPE_CHECKING:
    from starlette.types import Scope


LOGGER = logging.getLogger(__name__)

MAXIMUM_MESSAGE_SIZE = 4 * 1024 * 1024  # 4MB, matching HTTP transport
_MAX_LOG_LENGTH = 500


@dataclass(frozen=True)
class _MessageTooLarge:
    type: Literal["message_too_large"] = "message_too_large"


async def _read_line(reader: asyncio.StreamReader) -> bytes | _MessageTooLarge:
    """Read one line. `StreamReader` reports a line over its limit with `ValueError`."""
    try:
        return await reader.readline()
    except ValueError:
        LOGGER.exception("STDIO message exceeded maximum size of %d bytes", MAXIMUM_MESSAGE_SIZE)
        return _MessageTooLarge()


def _is_notification(json_message: object) -> bool:
    """Return True for JSON-RPC notifications, which must not receive a response."""
    if not isinstance(json_message, dict):
        return False
    method = json_message.get("method")
    return (
        isinstance(method, str)
        and method.startswith("notifications/")
        and json_message.get("id") is None
    )


class StdioTransport(BaseTransport):
    def __init__(self, server: ServerInterface) -> None:
        super().__init__(server)

    async def start(self, request_headers: dict[str, str] | None = None) -> None:
        """Start listening for messages on stdin."""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=MAXIMUM_MESSAGE_SIZE)
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin,
            sys.stdout,
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, loop)

        while not reader.at_eof():
            match await _read_line(reader):
                case _MessageTooLarge():
                    await self._write_message(
                        writer,
                        error_response(None, ErrorCode.INVALID_PARAMS, "Message too large"),
                    )
                    break
                case bytes() as line:
                    await self._handle_line(line.strip(), writer, request_headers)
                case _ as unreachable:
                    assert_never(unreachable)

    async def _handle_line(
        self,
        line: bytes,
        writer: asyncio.StreamWriter,
        request_headers: dict[str, str] | None,
    ) -> None:
        if not line:
            return

        LOGGER.debug("Received message: %s", line[:_MAX_LOG_LENGTH])
        match parse_json(line):
            case InvalidJson():
                await self._write_message(
                    writer,
                    error_response(None, ErrorCode.INVALID_PARAMS, "Parse error"),
                )
            case Parsed(value=json_message):
                if not _is_notification(json_message):
                    await self._handle_json(json_message, writer, request_headers)
            case _ as unreachable:
                assert_never(unreachable)

    async def _handle_json(
        self,
        json_message: object,
        writer: asyncio.StreamWriter,
        request_headers: dict[str, str] | None,
    ) -> None:
        match parse_model(JSONRPCRequest, json_message):
            case InvalidModel(description=description):
                LOGGER.error("STDIO request validation error")
                await self._write_message(
                    writer,
                    error_response(None, ErrorCode.INVALID_PARAMS, description),
                )
            case Parsed(value=message):
                await self._handle_message(message, writer, request_headers)
            case _ as unreachable:
                assert_never(unreachable)

    async def _write_response(
        self,
        writer: asyncio.StreamWriter,
        response: str,
    ) -> None:
        """Write a JSON-RPC response to stdout."""
        LOGGER.debug("Sending response: %s", response[:_MAX_LOG_LENGTH])
        writer.write(response.encode("utf-8"))
        writer.write(b"\n")
        await writer.drain()

    async def _write_message(
        self,
        writer: asyncio.StreamWriter,
        message: JSONRPCMessage,
    ) -> None:
        await self._write_response(
            writer,
            message.model_dump_json(by_alias=True, exclude_none=True),
        )

    async def _handle_message(
        self,
        message: JSONRPCRequest,
        writer: asyncio.StreamWriter,
        request_headers: dict[str, str] | None = None,
    ) -> None:
        asgi_headers: list[tuple[bytes, bytes]] = (
            [(k.lower().encode(), v.encode()) for k, v in request_headers.items()]
            if request_headers
            else []
        )
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "headers": asgi_headers,
            "path": "/",
            "client": ("127.0.0.1", 0),
            "server": ("127.0.0.1", 0),
            "root_path": "",
        }
        await self._write_message(writer, await self._respond(message, Request(scope)))

    async def _respond(self, message: JSONRPCRequest, request: Request) -> JSONRPCMessage:
        try:
            outcome = await self._process_request(message, request)
        except Exception:
            LOGGER.exception("Unexpected error processing STDIO request")
            return error_response(message.id, ErrorCode.INTERNAL_ERROR, "Internal server error")

        match outcome:
            case InsufficientScope(required_scopes=required_scopes):
                required = " ".join(required_scopes) if required_scopes else "unknown"
                return error_response(
                    message.id,
                    ErrorCode.INVALID_PARAMS,
                    f"Insufficient scope; required: {required}",
                )
            case Dispatched(response=response):
                return response
            case _ as unreachable:
                assert_never(unreachable)
