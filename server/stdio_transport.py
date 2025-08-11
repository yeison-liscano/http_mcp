import asyncio
import json
import logging
import sys
from typing import TYPE_CHECKING, Any

from mcp.types import (
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
)
from pydantic import ValidationError
from starlette.requests import Request

from server.server_interface import ServerInterface
from server.transport_base import BaseTransport

if TYPE_CHECKING:
    from starlette.types import Scope


LOGGER = logging.getLogger(__name__)


class StdioTransport(BaseTransport):
    def __init__(self, server: ServerInterface) -> None:
        super().__init__(server)

    async def start(self, request_headers: dict[str, str] | None = None) -> None:
        """Start listening for messages on stdin."""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin,
            sys.stdout,
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, loop)

        while not reader.at_eof():
            line = await reader.readline()
            if not line:
                continue

            line = line.strip()
            if not line:
                continue

            LOGGER.debug("Received message: %s", line)
            try:
                message = JSONRPCMessage.model_validate_json(line)
            except json.JSONDecodeError:
                error_response = JSONRPCError(
                    jsonrpc="2.0",
                    id=0,
                    error=ErrorData(code=-32700, message="Parse error"),
                )
                await self._write_response(writer, error_response.model_dump())
                continue

            await self._handle_message(message, writer, request_headers)

    async def _write_response(
        self,
        writer: asyncio.StreamWriter,
        response: dict[str, Any] | list[dict[str, Any]],
    ) -> None:
        """Write a JSON-RPC response to stdout."""
        response_str = json.dumps(response)
        LOGGER.debug("Sending response: %s", response_str)
        writer.write(response_str.encode("utf-8"))
        writer.write(b"\n")
        await writer.drain()

    async def _handle_message(
        self,
        message: JSONRPCMessage,
        writer: asyncio.StreamWriter,
        request_headers: dict[str, str] | None = None,
    ) -> None:
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "headers": request_headers or [],
            "path": "/",
            "client": ("127.0.0.1", 0),
            "server": ("127.0.0.1", 0),
            "root_path": "",
        }
        dummy_request = Request(scope)

        async def process(msg: JSONRPCMessage) -> JSONRPCResponse | JSONRPCError | None:
            msg_dict = msg.model_dump()
            if msg_dict.get("method", "").startswith("notifications/"):
                return None
            try:
                validated_msg = JSONRPCRequest.model_validate(msg_dict)
                return await self._process_request(validated_msg, dummy_request)
            except ValidationError:
                return JSONRPCError(
                    jsonrpc="2.0",
                    id=msg.id,  # type: ignore[attr-defined]
                    error=ErrorData(code=-32600, message="Invalid Request"),
                )

        response = await process(message)
        if response:
            await self._write_response(writer, response.model_dump())
