import asyncio
import json

import pytest

from http_mcp._transport_types import ProtocolErrorCode


@pytest.mark.asyncio
async def test_studio_transport() -> None:
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.app.main import run_stdio; run_stdio()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, stderr_data = await process.communicate(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {
                        "roots": {"listChanged": True},
                        "sampling": {},
                        "elicitation": {},
                    },
                    "clientInfo": {
                        "name": "ExampleClient",
                        "title": "Example Client Display Name",
                        "version": "1.0.0",
                    },
                },
            },
        ).encode("utf-8"),
    )

    assert not stderr_data
    assert json.loads(stdout_data) == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "serverInfo": {"name": "test", "version": "1.0.0"},
            "capabilities": {
                "prompts": {"listChanged": False, "subscribe": False},
                "tools": {"listChanged": False, "subscribe": False},
            },
            "protocolVersion": "2025-06-18",
        },
    }

    await process.wait()


@pytest.mark.asyncio
async def test_studio_transport_invalid_request() -> None:
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.app.main import run_stdio; run_stdio()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, stderr_data = await process.communicate(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
            },
        ).encode("utf-8"),
    )
    assert not stderr_data
    assert json.loads(stdout_data) == {
        "jsonrpc": "2.0",
        "error": {
            "code": ProtocolErrorCode.INVALID_PARAMS.value,
            "message": '[{"type": "missing", "loc": ["method"], "msg": "Field required", '
            '"input": {"jsonrpc": "2.0", "id": 1}, "url": '
            '"https://errors.pydantic.dev/2.11/v/missing"}]',
        },
    }


@pytest.mark.asyncio
async def test_studio_transport_invalid_body() -> None:
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.app.main import run_stdio; run_stdio()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, stderr_data = await process.communicate(
        b"invalid body",
    )
    assert not stderr_data
    assert json.loads(stdout_data) == {
        "jsonrpc": "2.0",
        "error": {
            "code": ProtocolErrorCode.INVALID_PARAMS.value,
            "message": "Parse error",
        },
    }


@pytest.mark.asyncio
async def test_studio_transport_notification() -> None:
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.app.main import run_stdio; run_stdio()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, stderr_data = await process.communicate(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        ).encode("utf-8"),
    )
    assert not stderr_data
    assert not stdout_data


@pytest.mark.asyncio
async def test_studio_transport_no_content() -> None:
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.app.main import run_stdio; run_stdio()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, stderr_data = await process.communicate(b"   ")
    assert not stderr_data
    assert not stdout_data
