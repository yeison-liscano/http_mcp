import asyncio
import contextlib
import logging
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, assert_never

from starlette.requests import Request

from http_mcp._json_rcp_types.errors import ErrorCode
from http_mcp._json_rcp_types.messages import (
    JSONRPCMessage,
    JSONRPCRequest,
)
from http_mcp._parsing import InvalidJson, InvalidModel, Parsed, parse_json, parse_model
from http_mcp._transport_base import BaseTransport, Dispatched, error_response, request_id
from http_mcp.failures import InsufficientScope
from http_mcp.server_interface import ServerInterface

if TYPE_CHECKING:
    from starlette.types import Scope


LOGGER = logging.getLogger(__name__)

MAXIMUM_MESSAGE_SIZE = 4 * 1024 * 1024  # 4MB, matching HTTP transport
_MAX_LOG_LENGTH = 500
_LINE_SEPARATOR = b"\n"


@dataclass(frozen=True)
class _MessageTooLarge:
    type: Literal["message_too_large"] = "message_too_large"


async def _skip_rest_of_line(reader: asyncio.StreamReader) -> None:
    """Consume input up to and including the next newline, never buffering past the limit.

    `readuntil` leaves an overlong line in the buffer and reports how much of it can be
    dropped, so the line is discarded a buffer-full at a time until its newline arrives.
    """
    while True:
        try:
            await reader.readuntil(_LINE_SEPARATOR)
        except asyncio.LimitOverrunError as overrun:
            discardable = overrun.consumed
        except asyncio.IncompleteReadError:
            return
        else:
            return
        try:
            await reader.readexactly(discardable)
        except asyncio.IncompleteReadError:
            return


async def _read_line(reader: asyncio.StreamReader) -> bytes | _MessageTooLarge:
    """Read one line, or report one longer than the limit after skipping past it.

    `StreamReader.readline` clears its buffer on an overlong line without consuming the
    rest of it, so the tail would come back as a message of its own. Skipping to the
    next newline keeps the framing intact, and the session can go on serving requests.
    """
    try:
        return await reader.readuntil(_LINE_SEPARATOR)
    except asyncio.IncompleteReadError as end_of_input:
        # End of input. Whatever came after the last newline is the final line.
        return end_of_input.partial
    except asyncio.LimitOverrunError:
        LOGGER.error("STDIO message exceeded maximum size of %d bytes", MAXIMUM_MESSAGE_SIZE)  # noqa: TRY400
    await _skip_rest_of_line(reader)
    return _MessageTooLarge()


@contextlib.contextmanager
def _stdout_reserved_for_protocol() -> Iterator[int]:
    """Yield a descriptor for the real stdout, and point the process's stdout at stderr.

    Tool and prompt functions run in this process. Anything they write to stdout, through
    `print`, a library, or a child process that inherits the descriptor, would otherwise
    land between protocol frames, where the client reads it as a message of its own.
    The yielded descriptor belongs to the caller, which must close it.
    """
    sys.stdout.flush()
    stdout_fd = sys.stdout.fileno()
    protocol_fd = os.dup(stdout_fd)
    saved_fd = os.dup(stdout_fd)
    os.dup2(sys.stderr.fileno(), stdout_fd)
    try:
        yield protocol_fd
    finally:
        sys.stdout.flush()
        os.dup2(saved_fd, stdout_fd)
        os.close(saved_fd)


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

        with _stdout_reserved_for_protocol() as protocol_fd:
            writer_transport, writer_protocol = await loop.connect_write_pipe(
                asyncio.streams.FlowControlMixin,
                os.fdopen(protocol_fd, "wb", buffering=0),
            )
            writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, loop)
            try:
                await self._serve(reader, writer, request_headers)
            finally:
                writer.close()

    async def _serve(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        request_headers: dict[str, str] | None,
    ) -> None:
        while not reader.at_eof():
            match await _read_line(reader):
                case _MessageTooLarge():
                    await self._write_message(
                        writer,
                        error_response(None, ErrorCode.INVALID_PARAMS, "Message too large"),
                    )
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
                    error_response(None, ErrorCode.PARSE_ERROR, "Parse error"),
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
                    error_response(request_id(json_message), ErrorCode.INVALID_PARAMS, description),
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
            case InsufficientScope():
                # STDIO has no step-up flow for the scope names to drive, so naming them
                # would only tell the caller what the hidden tool or prompt requires.
                return error_response(message.id, ErrorCode.INVALID_PARAMS, "Insufficient scope")
            case Dispatched(response=response):
                return response
            case _ as unreachable:
                assert_never(unreachable)
