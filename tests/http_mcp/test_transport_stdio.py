import asyncio
import json

import pytest

from http_mcp._json_rcp_types.errors import ErrorCode
from http_mcp._mcp_types.versions import SUPPORTED_PROTOCOL_VERSIONS
from tests.fixtures.protocol import request_meta, without_envelope


@pytest.mark.asyncio
async def test_studio_transport_discover() -> None:
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.fixtures.main import run_stdio; run_stdio()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, stderr_data = await process.communicate(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {"_meta": request_meta()},
            },
        ).encode("utf-8"),
    )

    assert not stderr_data
    assert without_envelope(json.loads(stdout_data)) == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "supportedVersions": list(SUPPORTED_PROTOCOL_VERSIONS),
            "capabilities": {
                "prompts": {"listChanged": False},
                "tools": {"listChanged": False},
            },
        },
    }

    await process.wait()


@pytest.mark.asyncio
async def test_studio_transport_invalid_request() -> None:
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.fixtures.main import run_stdio; run_stdio()",
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
    assert b"STDIO request validation error" in stderr_data
    assert json.loads(stdout_data) == {
        "jsonrpc": "2.0",
        "error": {
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": '[{"field": "method", "message": "Field required"}]',
        },
    }


@pytest.mark.asyncio
async def test_studio_transport_invalid_body() -> None:
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.fixtures.main import run_stdio; run_stdio()",
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
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": "Parse error",
        },
    }


@pytest.mark.asyncio
async def test_studio_transport_notification() -> None:
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.fixtures.main import run_stdio; run_stdio()",
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
async def test_studio_transport_rejects_retired_method() -> None:
    """`ping` was removed with the session concept; it is now an unknown method."""
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.fixtures.main import run_stdio; run_stdio()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, _ = await process.communicate(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8"),
    )
    assert json.loads(stdout_data)["error"]["code"] == ErrorCode.INVALID_PARAMS.value


@pytest.mark.asyncio
async def test_studio_transport_no_content() -> None:
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.fixtures.main import run_stdio; run_stdio()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, stderr_data = await process.communicate(b"   ")
    assert not stderr_data
    assert not stdout_data
