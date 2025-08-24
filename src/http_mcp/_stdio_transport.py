import asyncio
import json
import logging
import sys
from typing import TYPE_CHECKING

from pydantic import ValidationError
from starlette.requests import Request

from http_mcp._transport_base import BaseTransport
from http_mcp._transport_types import ProtocolErrorCode
from http_mcp.mcp_types.messages import (
    Error,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
)
from http_mcp.server_interface import ServerInterface

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
            json_message = {}
            try:
                json_message = json.loads(line)
                await self._handle_message(
                    JSONRPCRequest.model_validate(json_message),
                    writer,
                    request_headers,
                )
            except ValidationError as e:
                error_response = JSONRPCError(
                    jsonrpc="2.0",
                    error=Error(
                        code=ProtocolErrorCode.INVALID_PARAMS.value,
                        message=json.dumps(e.errors()),
                    ),
                )
                await self._write_response(
                    writer,
                    error_response.model_dump_json(by_alias=True, exclude_none=True),
                )
            except json.JSONDecodeError:
                error_response = JSONRPCError(
                    jsonrpc="2.0",
                    error=Error(
                        code=ProtocolErrorCode.INVALID_PARAMS.value,
                        message="Parse error",
                    ),
                )
                await self._write_response(
                    writer,
                    error_response.model_dump_json(by_alias=True, exclude_none=True),
                )
                continue

    async def _write_response(
        self,
        writer: asyncio.StreamWriter,
        response: str,
    ) -> None:
        """Write a JSON-RPC response to stdout."""
        LOGGER.debug("Sending response: %s", response)
        writer.write(response.encode("utf-8"))
        writer.write(b"\n")
        await writer.drain()

    async def _handle_message(
        self,
        message: JSONRPCRequest,
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

        async def process(msg: JSONRPCRequest) -> JSONRPCMessage | JSONRPCError | None:
            if msg.method.startswith("notifications/"):
                return None

            return await self._process_request(msg, dummy_request)

        response = await process(message)
        if response:
            await self._write_response(
                writer,
                response.model_dump_json(by_alias=True, exclude_none=True),
            )
