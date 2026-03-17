"""Tests for realistic stateful tool patterns.

These tests demonstrate practical state management scenarios without
order-coupled assertions inside tool functions.
"""

from __future__ import annotations

import asyncio
import contextlib
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, TypedDict

from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.testclient import TestClient

from http_mcp.server import MCPServer
from http_mcp.types import Arguments, NoArguments, Tool
from tests.fixtures.context import Context
from tests.fixtures.main import mount_mcp_server, mount_mcp_server_multi_state
from tests.fixtures.tools import STATEFUL_TOOLS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _call_tool(client: TestClient, name: str, arguments: dict[str, str]) -> dict[str, Any]:
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == HTTPStatus.OK
    return response.json()


def test_tool_reads_state_written_by_another_tool() -> None:
    server = MCPServer(tools=STATEFUL_TOOLS, name="test", version="1.0.0")
    app = mount_mcp_server(server)

    with TestClient(app) as client:
        # Write a note
        add_result = _call_tool(client, "add_note", {"topic": "python", "note": "use type hints"})
        assert add_result["result"]["isError"] is False
        assert add_result["result"]["structuredContent"]["notes"] == ["use type hints"]

        # Read it back from a different tool
        get_result = _call_tool(client, "get_notes", {"topic": "python"})
        assert get_result["result"]["isError"] is False
        assert get_result["result"]["structuredContent"]["notes"] == ["use type hints"]

        # Verify the counter was incremented by the write
        count_result = _call_tool(client, "get_request_count", {})
        assert count_result["result"]["structuredContent"]["count"] == 1


def test_multiple_writes_accumulate_in_shared_state() -> None:
    server = MCPServer(tools=STATEFUL_TOOLS, name="test", version="1.0.0")
    app = mount_mcp_server(server)

    with TestClient(app) as client:
        # Add two notes to the same topic
        _call_tool(client, "add_note", {"topic": "python", "note": "use type hints"})
        _call_tool(client, "add_note", {"topic": "python", "note": "prefer immutability"})

        get_result = _call_tool(client, "get_notes", {"topic": "python"})
        assert get_result["result"]["structuredContent"]["notes"] == [
            "use type hints",
            "prefer immutability",
        ]

        # Set two cache entries
        _call_tool(client, "set_cache", {"key": "lang", "value": "python"})
        _call_tool(client, "set_cache", {"key": "version", "value": "3.13"})

        lang = _call_tool(client, "get_cache", {"key": "lang"})
        assert lang["result"]["structuredContent"]["value"] == "python"

        version = _call_tool(client, "get_cache", {"key": "version"})
        assert version["result"]["structuredContent"]["value"] == "3.13"

        # Counter reflects all 4 write operations (2 add_note + 2 set_cache)
        expected_write_count = 4
        count_result = _call_tool(client, "get_request_count", {})
        assert count_result["result"]["structuredContent"]["count"] == expected_write_count


def test_state_isolation_between_sessions() -> None:
    server = MCPServer(tools=STATEFUL_TOOLS, name="test", version="1.0.0")

    # Each app gets its own lifespan → its own Context
    app_1 = mount_mcp_server(server)
    app_2 = mount_mcp_server(server)

    with TestClient(app_1) as client_1, TestClient(app_2) as client_2:
        # Write a note in session 1
        _call_tool(client_1, "add_note", {"topic": "python", "note": "session 1 note"})

        # Session 2 should see an empty list for the same topic
        result_2 = _call_tool(client_2, "get_notes", {"topic": "python"})
        assert result_2["result"]["structuredContent"]["notes"] == []

        # Write a different note in session 2
        _call_tool(client_2, "add_note", {"topic": "python", "note": "session 2 note"})

        # Each session sees only its own notes
        result_1 = _call_tool(client_1, "get_notes", {"topic": "python"})
        assert result_1["result"]["structuredContent"]["notes"] == ["session 1 note"]

        result_2 = _call_tool(client_2, "get_notes", {"topic": "python"})
        assert result_2["result"]["structuredContent"]["notes"] == ["session 2 note"]


def test_multiple_state_keys_on_same_lifespan() -> None:
    class WriteToSecondaryOutput(BaseModel):
        success: bool = Field(description="Whether the write succeeded", default=True)

    async def write_to_secondary(args: Arguments[NoArguments]) -> WriteToSecondaryOutput:
        """Write to the secondary context."""
        secondary = args.get_state_key("secondary_context", Context)
        secondary.add_note("test", "written to secondary")
        return WriteToSecondaryOutput()

    class ReadSecondaryOutput(BaseModel):
        notes: list[str] = Field(description="Notes from the secondary context")

    async def read_secondary(args: Arguments[NoArguments]) -> ReadSecondaryOutput:
        """Read from the secondary context."""
        secondary = args.get_state_key("secondary_context", Context)
        return ReadSecondaryOutput(notes=secondary.get_notes("test"))

    tools = (
        *STATEFUL_TOOLS,
        Tool(func=write_to_secondary, inputs=NoArguments, output=WriteToSecondaryOutput),
        Tool(func=read_secondary, inputs=NoArguments, output=ReadSecondaryOutput),
    )
    server = MCPServer(tools=tools, name="test", version="1.0.0")
    app = mount_mcp_server_multi_state(server)

    with TestClient(app) as client:
        # Write to secondary context
        _call_tool(client, "write_to_secondary", {})

        # Read from secondary — should have the note
        result = _call_tool(client, "read_secondary", {})
        assert result["result"]["structuredContent"]["notes"] == ["written to secondary"]

        # Primary context should be unaffected
        primary_notes = _call_tool(client, "get_notes", {"topic": "test"})
        assert primary_notes["result"]["structuredContent"]["notes"] == []


def test_state_with_async_initialization() -> None:
    class AsyncState(TypedDict):
        context: Context

    @contextlib.asynccontextmanager
    async def async_lifespan(_app: Starlette) -> AsyncIterator[AsyncState]:
        # Simulate async resource initialization (e.g., connection pool)
        await asyncio.sleep(0)
        ctx = Context()
        ctx.set_cache("initialized", "true")
        yield {"context": ctx}

    server = MCPServer(tools=STATEFUL_TOOLS, name="test", version="1.0.0")
    app = Starlette(lifespan=async_lifespan)
    app.mount("/mcp", server.app)

    with TestClient(app) as client:
        # The async-initialized value should be available
        result = _call_tool(client, "get_cache", {"key": "initialized"})
        assert result["result"]["structuredContent"]["value"] == "true"


def test_cache_miss_returns_none() -> None:
    server = MCPServer(tools=STATEFUL_TOOLS, name="test", version="1.0.0")
    app = mount_mcp_server(server)

    with TestClient(app) as client:
        result = _call_tool(client, "get_cache", {"key": "nonexistent"})
        assert result["result"]["isError"] is False
        assert result["result"]["structuredContent"]["value"] is None


def test_get_state_key_type_mismatch_raises_server_error() -> None:
    class WrongType:
        pass

    class MismatchOutput(BaseModel):
        value: str = Field(description="Unreachable")

    def tool_with_wrong_type(args: Arguments[NoArguments]) -> MismatchOutput:
        """Request state with the wrong type."""
        args.get_state_key("context", WrongType)
        return MismatchOutput(value="unreachable")

    server = MCPServer(
        name="test",
        version="1.0.0",
        tools=(Tool(func=tool_with_wrong_type, inputs=NoArguments, output=MismatchOutput),),
    )
    app = mount_mcp_server(server)

    with TestClient(app) as client:
        result = _call_tool(client, "tool_with_wrong_type", {})
        assert result["result"]["isError"] is True
        error_text = result["result"]["content"][0]["text"]
        assert "type mismatch" in error_text
        # Internal class names should NOT be leaked
        assert "WrongType" not in error_text
        assert "Context" not in error_text
