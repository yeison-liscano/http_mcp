import asyncio
import json
import sys
from decimal import Decimal
from http import HTTPStatus

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field, RootModel, computed_field
from starlette.testclient import TestClient

from http_mcp._json_rcp_types.errors import Error, ErrorCode
from http_mcp.exceptions import ServerError, ToolInvocationError
from http_mcp.server import MCPServer
from http_mcp.types import Arguments, NoArguments, Prompt, PromptMessage, Tool, ToolAnnotations
from http_mcp.types.models import ErrorMessage
from tests.fixtures.models import DUMMY_TOOL
from tests.fixtures.prompts import PROMPTS
from tests.fixtures.protocol import MCPTestClient, with_envelope


class AliasedInput(BaseModel):
    value: str = Field(alias="wireValue")


class AliasedOutput(BaseModel):
    value: str = Field(serialization_alias="wireValue")
    price: Decimal = Decimal("1.25")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        return self.value.upper()


def echo_alias(args: Arguments[AliasedInput]) -> AliasedOutput:
    return AliasedOutput(value=args.inputs.value)


def test_published_schemas_match_validated_inputs_and_serialized_outputs() -> None:
    client = MCPTestClient(
        MCPServer("test", "1", (Tool(echo_alias, AliasedInput, AliasedOutput),)).app,
    )
    listed = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    ).json()["result"]["tools"][0]
    arguments = {"wireValue": "ok"}
    Draft202012Validator(listed["inputSchema"]).validate(arguments)

    response = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "echo_alias", "arguments": arguments},
        },
    )
    assert response.status_code == HTTPStatus.OK
    result = response.json()["result"]
    expected = {"wireValue": "ok", "price": "1.25", "label": "OK"}
    assert result["structuredContent"] == expected
    assert json.loads(result["content"][0]["text"]) == expected
    Draft202012Validator(listed["outputSchema"]).validate(result["structuredContent"])


@pytest.mark.parametrize(
    ("output", "value"),
    [
        (RootModel[list[int]], [1, 2]),
        (RootModel[int], 42),
        (RootModel[str], "ok"),
        (RootModel[bool], False),
        (RootModel[None], None),
    ],
)
@pytest.mark.parametrize("return_error_message", [False, True])
def test_root_outputs_conform_to_their_published_schemas(
    output: type[BaseModel],
    value: object,
    *,
    return_error_message: bool,
) -> None:
    def root_output() -> BaseModel:
        return output.model_validate(value)

    tool = Tool(root_output, type(None), output, return_error_message=return_error_message)
    client = MCPTestClient(MCPServer("test", "1", (tool,)).app)
    response = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool.name}},
    )

    assert response.status_code == HTTPStatus.OK
    result = response.json()["result"]
    assert "structuredContent" in result
    assert result["structuredContent"] == value
    assert json.loads(result["content"][0]["text"]) == value
    Draft202012Validator(tool.output_schema).validate(value)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"id": None}, ErrorCode.INVALID_REQUEST),
        ({"id": True}, ErrorCode.INVALID_REQUEST),
        ({"id": 1.0}, ErrorCode.INVALID_REQUEST),
        ({"jsonrpc": "1.0"}, ErrorCode.INVALID_REQUEST),
        ({"method": "unknown"}, ErrorCode.METHOD_NOT_FOUND),
        ({"params": []}, ErrorCode.INVALID_PARAMS),
    ],
)
def test_http_request_error_categories(changes: dict, code: ErrorCode) -> None:
    body, headers = with_envelope({"jsonrpc": "2.0", "id": 1, "method": "server/discover"})
    body.update(changes)
    headers["Mcp-Method"] = body["method"]
    response = TestClient(MCPServer("test", "1").app).post("/", json=body, headers=headers)

    assert response.json()["error"]["code"] == code
    assert response.status_code == (
        HTTPStatus.NOT_FOUND if code == ErrorCode.METHOD_NOT_FOUND else HTTPStatus.BAD_REQUEST
    )


@pytest.mark.parametrize("method", ["server/discover", "tools/call", "unknown"])
def test_http_notifications_do_not_invoke_request_methods(method: str) -> None:
    calls: list[str] = []

    def record_call() -> NoArguments:
        calls.append("called")
        return NoArguments()

    server = MCPServer("test", "1", (Tool(record_call, type(None), NoArguments),))
    body, headers = with_envelope(
        {"jsonrpc": "2.0", "method": method, "params": {"name": "record_call"}},
    )
    response = TestClient(server.app).post("/", json=body, headers=headers)

    assert response.status_code == HTTPStatus.ACCEPTED
    assert response.content == b""
    assert calls == []


@pytest.mark.asyncio
async def test_stdio_classifies_errors_and_never_answers_notifications() -> None:
    requests = (
        {"jsonrpc": "2.0", "method": "server/discover"},
        {"jsonrpc": "2.0", "method": "unknown"},
        {"jsonrpc": "2.0", "id": None, "method": "server/discover"},
        {"jsonrpc": "1.0", "id": 2, "method": "server/discover"},
        {"jsonrpc": "2.0", "id": 3, "method": "unknown"},
        {"jsonrpc": "2.0", "id": 4, "method": "server/discover", "params": []},
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "from tests.fixtures.main import run_stdio; run_stdio()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(
        process.communicate(b"\n".join(json.dumps(body).encode() for body in requests)),
        timeout=10,
    )
    errors = tuple(json.loads(line)["error"]["code"] for line in stdout.splitlines())
    assert errors == (
        ErrorCode.INVALID_REQUEST,
        ErrorCode.INVALID_REQUEST,
        ErrorCode.METHOD_NOT_FOUND,
        ErrorCode.INVALID_PARAMS,
    )


@pytest.mark.parametrize("cursor", [1, True, {}, "-1", "9999", "not-a-cursor"])
@pytest.mark.parametrize("method", ["tools/list", "prompts/list"])
def test_list_methods_reject_invalid_cursors(cursor: object, method: str) -> None:
    client = MCPTestClient(MCPServer("test", "1", (DUMMY_TOOL,), prompts=PROMPTS).app)
    response = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": {"cursor": cursor}},
    )
    assert response.json()["error"]["code"] == ErrorCode.INVALID_PARAMS


@pytest.mark.parametrize("tools_enabled", [False, True])
@pytest.mark.parametrize("prompts_enabled", [False, True])
def test_methods_match_advertised_capabilities(
    *,
    tools_enabled: bool,
    prompts_enabled: bool,
) -> None:
    def no_arguments() -> NoArguments:
        return NoArguments()

    def no_messages() -> tuple[PromptMessage, ...]:
        return ()

    tool = Tool(no_arguments, type(None), NoArguments)
    prompt = Prompt(no_messages, type(None))
    client = MCPTestClient(
        MCPServer(
            "test",
            "1",
            tools=(tool,) if tools_enabled else (),
            prompts=(prompt,) if prompts_enabled else (),
        ).app,
    )
    capabilities = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
    ).json()["result"]["capabilities"]
    assert ("tools" in capabilities) is tools_enabled
    assert ("prompts" in capabilities) is prompts_enabled
    for method, enabled, params in (
        ("tools/list", tools_enabled, {}),
        ("tools/call", tools_enabled, {"name": tool.name}),
        ("prompts/list", prompts_enabled, {}),
        ("prompts/get", prompts_enabled, {"name": prompt.name}),
    ):
        response = client.post(
            "/",
            json={"jsonrpc": "2.0", "id": 2, "method": method, "params": params},
        )
        if enabled:
            assert response.status_code == HTTPStatus.OK
            assert "result" in response.json()
        else:
            assert response.status_code == HTTPStatus.NOT_FOUND
            assert response.json()["error"]["code"] == ErrorCode.METHOD_NOT_FOUND


@pytest.mark.asyncio
async def test_stdio_rejects_unadvertised_capabilities() -> None:
    requests = tuple(
        with_envelope({"jsonrpc": "2.0", "id": index, "method": method})[0]
        for index, method in enumerate(("tools/list", "tools/call", "prompts/list", "prompts/get"))
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import asyncio; from http_mcp.server import MCPServer; "
        "asyncio.run(MCPServer('empty', '1').serve_stdio())",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(
        process.communicate(b"\n".join(json.dumps(body).encode() for body in requests)),
        timeout=10,
    )
    assert tuple(json.loads(line)["error"]["code"] for line in stdout.splitlines()) == (
        ErrorCode.METHOD_NOT_FOUND,
    ) * len(requests)


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            ToolInvocationError("fail", "expected feedback"),
            "Error calling tool fail: expected feedback",
        ),
        (
            ServerError(Error(code=ErrorCode.INTERNAL_ERROR, description="State is missing")),
            "State is missing",
        ),
        (RuntimeError("private exception detail"), "Error calling tool fail: Unknown error"),
    ],
)
def test_structured_errors_preserve_data_and_failure_semantics(
    failure: Exception,
    expected: str,
) -> None:
    def fail() -> NoArguments:
        raise failure

    tool = Tool(fail, type(None), NoArguments, return_error_message=True)
    response = MCPTestClient(MCPServer("test", "1", (tool,)).app).post(
        "/",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool.name}},
    )
    assert response.status_code == HTTPStatus.OK
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"] == {"error_message": expected}
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    Draft202012Validator(tool.output_schema).validate(result["structuredContent"])


def test_returned_error_model_is_distinct_from_failed_invocation() -> None:
    def data() -> ErrorMessage:
        return ErrorMessage(error_message="ordinary returned data")

    tool = Tool(data, type(None), ErrorMessage)
    result = (
        MCPTestClient(MCPServer("test", "1", (tool,)).app)
        .post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool.name}},
        )
        .json()["result"]
    )
    assert result["isError"] is False


@pytest.mark.parametrize(
    ("annotations", "expected"),
    [
        (ToolAnnotations(), {"title": "Echo Alias"}),
        (ToolAnnotations(read_only_hint=False), {"title": "Echo Alias", "readOnlyHint": False}),
        (
            ToolAnnotations(
                title="Write record",
                read_only_hint=False,
                destructive_hint=True,
                idempotent_hint=False,
                open_world_hint=True,
            ),
            {
                "title": "Write record",
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        ),
    ],
)
def test_explicit_annotations_are_published_without_unspecified_safety_claims(
    annotations: ToolAnnotations,
    expected: dict,
) -> None:
    tool = Tool(echo_alias, AliasedInput, AliasedOutput, annotations=annotations)
    result = (
        MCPTestClient(MCPServer("test", "1", (tool,)).app)
        .post(
            "/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        .json()["result"]
    )
    assert result["tools"][0]["annotations"] == expected
