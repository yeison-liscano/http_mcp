import asyncio
import json

import pytest

from http_mcp._json_rcp_types.errors import ErrorCode
from http_mcp._mcp_types.versions import SUPPORTED_PROTOCOL_VERSIONS
from http_mcp._stdio_transport import MAXIMUM_MESSAGE_SIZE, _read_line
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
        "id": 1,
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
            "code": ErrorCode.PARSE_ERROR.value,
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "undecodable_line",
    [
        pytest.param(b"\xff\xfe{", id="not-utf-8"),
        pytest.param(b"[" * 200_000, id="nested-past-the-recursion-limit"),
        pytest.param(b"1" * 5_000, id="integer-past-the-digit-limit"),
    ],
)
async def test_studio_transport_survives_an_undecodable_line(undecodable_line: bytes) -> None:
    """One bad line reports a parse error; the server keeps serving the next request."""
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        "from tests.fixtures.main import run_stdio; run_stdio()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    valid_request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {"_meta": request_meta()},
        },
    ).encode("utf-8")

    stdout_data, stderr_data = await process.communicate(
        undecodable_line + b"\n" + valid_request + b"\n",
    )

    assert not stderr_data
    parse_error, discover_response = stdout_data.splitlines()
    assert json.loads(parse_error) == {
        "jsonrpc": "2.0",
        "error": {"code": ErrorCode.PARSE_ERROR.value, "message": "Parse error"},
    }
    assert json.loads(discover_response)["id"] == 1
    await process.wait()


async def _run_stdio(entry_point: str, stdin: bytes) -> tuple[bytes, bytes]:
    module, function = entry_point.rsplit(".", 1)
    process = await asyncio.create_subprocess_exec(
        "python",
        "-c",
        f"from {module} import {function}; {function}()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, stderr_data = await process.communicate(stdin)
    await process.wait()
    return stdout_data, stderr_data


def _discover(message_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "server/discover",
            "params": {"_meta": request_meta()},
        },
    ).encode("utf-8")


_OVERSIZED_LINE = b'{"padding":"' + b"A" * MAXIMUM_MESSAGE_SIZE + b'"}'
_TOO_LARGE = {
    "jsonrpc": "2.0",
    "error": {"code": ErrorCode.INVALID_PARAMS.value, "message": "Message too large"},
}


@pytest.mark.asyncio
async def test_studio_transport_survives_oversized_lines() -> None:
    """An oversized line is skipped to its newline; the session keeps serving.

    It used to end the session, and its tail would otherwise come back as a message.
    """
    stdout_data, _ = await _run_stdio(
        "tests.fixtures.main.run_stdio",
        _OVERSIZED_LINE + b"\n" + _OVERSIZED_LINE + b"\n" + _discover(3) + b"\n",
    )

    first, second, discover_response = stdout_data.splitlines()
    assert json.loads(first) == _TOO_LARGE
    assert json.loads(second) == _TOO_LARGE
    assert json.loads(discover_response)["id"] == 3  # noqa: PLR2004


@pytest.mark.asyncio
async def test_studio_transport_reports_an_oversized_final_line() -> None:
    stdout_data, _ = await _run_stdio(
        "tests.fixtures.main.run_stdio",
        _discover(1) + b"\n" + _OVERSIZED_LINE,
    )

    discover_response, too_large = stdout_data.splitlines()
    assert json.loads(discover_response)["id"] == 1
    assert json.loads(too_large) == _TOO_LARGE


@pytest.mark.asyncio
async def test_studio_transport_does_not_name_the_scopes_a_hidden_tool_requires() -> None:
    """STDIO has no step-up flow, so the scope names would only describe the hidden tool."""
    request = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "private_tool", "arguments": {}, "_meta": request_meta()},
    }

    stdout_data, _ = await _run_stdio(
        "tests.fixtures.main.run_stdio",
        json.dumps(request).encode("utf-8") + b"\n",
    )

    assert json.loads(stdout_data) == {
        "jsonrpc": "2.0",
        "id": 5,
        "error": {"code": ErrorCode.INVALID_PARAMS.value, "message": "Insufficient scope"},
    }


@pytest.mark.asyncio
async def test_tool_output_on_stdout_cannot_forge_a_protocol_frame() -> None:
    """What tool code prints goes to stderr; stdout carries protocol frames only."""
    forged = json.dumps({"jsonrpc": "2.0", "id": 7, "result": {"forged": True}})
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"text": forged}, "_meta": request_meta()},
    }

    stdout_data, stderr_data = await _run_stdio(
        "tests.fixtures.noisy_stdio.run",
        json.dumps(request).encode("utf-8") + b"\n",
    )

    (response,) = stdout_data.splitlines()
    assert json.loads(response)["result"]["structuredContent"] == {"text": forged}
    assert forged.encode("utf-8") in stderr_data


# ---------------------------------------------------------------------------
# Line framing, in process
# ---------------------------------------------------------------------------

_LIMIT = 16


async def _frames(data: bytes) -> list[bytes | str]:
    """Feed `data` to a reader with a small limit and collect what `_read_line` yields."""
    reader = asyncio.StreamReader(limit=_LIMIT)
    reader.feed_data(data)
    reader.feed_eof()
    frames: list[bytes | str] = []
    while not reader.at_eof():
        match await _read_line(reader):
            case bytes() as line:
                frames.append(line)
            case _:
                frames.append("too large")
    return frames


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"ok\n", [b"ok\n"]),
        (b"ok", [b"ok"]),
        # The newline is already buffered past the limit.
        (b"x" * 40 + b"\nnext\n", ["too large", b"next\n"]),
        # The overlong line spans several buffer-fulls before its newline arrives.
        (b"x" * 200 + b"\nnext\n", ["too large", b"next\n"]),
        (b"x" * 200 + b"\n" + b"y" * 200 + b"\nnext\n", ["too large", "too large", b"next\n"]),
        # Input ends inside an overlong line.
        (b"first\n" + b"x" * 200, [b"first\n", "too large"]),
    ],
)
async def test_read_line_skips_overlong_lines_and_keeps_the_framing(
    data: bytes,
    expected: list[bytes | str],
) -> None:
    assert await _frames(data) == expected
