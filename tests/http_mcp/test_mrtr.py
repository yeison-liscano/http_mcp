import asyncio
import json
import sys
from http import HTTPStatus
from typing import Any

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from http_mcp._json_rcp_types.errors import ErrorCode
from http_mcp._mcp_types.meta import META_SERVER_INFO
from http_mcp.server import MCPServer
from http_mcp.types import (
    AcceptedElicitation,
    Arguments,
    ElicitationRequest,
    ElicitationSchema,
    FormElicitation,
    InputRequired,
    InvocationResult,
    NoArguments,
    RetryRequired,
    StringField,
    Tool,
    UrlElicitation,
)
from tests.fixtures.main import BasicAuthBackend, mount_mcp_server
from tests.fixtures.mrtr import Greeting, create_server, greeting
from tests.fixtures.protocol import MCPTestClient, request_meta


def _body(method: str = "tools/call", **extra: Any) -> dict:  # noqa: ANN401
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            "name": "greeting" if method == "tools/call" else "greeting_prompt",
            "arguments": {},
            "_meta": request_meta(capabilities={"elicitation": {}}),
            **extra,
        },
    }


@pytest.mark.parametrize("method", ["tools/call", "prompts/get"])
def test_mrtr_retry_on_independent_server(method: str) -> None:
    initial = MCPTestClient(create_server().app).post("/mcp", json=_body(method)).json()
    result = initial["result"]
    assert result["resultType"] == "input_required"
    assert result["_meta"][META_SERVER_INFO]["name"] == "mrtr-test"
    assert "structuredContent" not in result
    assert "messages" not in result
    assert result["inputRequests"] == {
        "profile": {
            "method": "elicitation/create",
            "params": {
                "mode": "form",
                "message": "What should we call you?",
                "requestedSchema": {
                    "type": "object",
                    "properties": {"nickname": {"type": "string"}},
                    "required": ["nickname"],
                },
            },
        },
    }
    retry = _body(
        method,
        requestState=result["requestState"],
        inputResponses={"profile": {"action": "accept", "content": {"nickname": "Ada"}}},
    )
    retry["id"] = "retry"
    response = MCPTestClient(create_server().app).post("/mcp", json=retry).json()
    assert response["id"] == "retry"
    assert response["result"]["resultType"] == "complete"
    if method == "tools/call":
        assert response["result"]["structuredContent"] == {"message": "Hello, Ada"}
    else:
        assert response["result"]["messages"][0]["content"]["text"] == "Hello, Ada"


@pytest.mark.parametrize(
    "capabilities",
    [{}, {"elicitation": None}, {"elicitation": True}],
)
@pytest.mark.parametrize("method", ["tools/call", "prompts/get"])
def test_capability_required_is_http_400(capabilities: dict, method: str) -> None:
    body = _body(method)
    body["params"]["_meta"] = request_meta(capabilities=capabilities)
    response = MCPTestClient(create_server().app).post("/mcp", json=body)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["error"]["code"] == ErrorCode.MISSING_REQUIRED_CLIENT_CAPABILITY
    assert response.json()["error"]["data"] == {
        "requiredCapabilities": {"elicitation": {"form": {}}},
    }
    assert "result" not in response.json()


@pytest.mark.parametrize("action", ["decline", "cancel"])
@pytest.mark.parametrize("method", ["tools/call", "prompts/get"])
def test_user_refusal_is_explicit(action: str, method: str) -> None:
    client = MCPTestClient(create_server().app)
    initial = client.post("/mcp", json=_body(method)).json()["result"]
    body = _body(
        method,
        requestState=initial["requestState"],
        inputResponses={"profile": {"action": action}},
    )
    result = client.post("/mcp", json=body).json()["result"]
    assert result["resultType"] == "complete"
    expected = "Declined" if action == "decline" else "Cancelled"
    if method == "tools/call":
        assert result["structuredContent"]["message"] == expected
    else:
        assert result["messages"][0]["content"]["text"] == expected


@pytest.mark.parametrize("method", ["tools/call", "prompts/get"])
def test_missing_input_is_requested_again_and_unknown_keys_are_ignored(method: str) -> None:
    client = MCPTestClient(create_server().app)
    initial = client.post("/mcp", json=_body(method)).json()["result"]
    response = client.post(
        "/mcp",
        json=_body(method, requestState=initial["requestState"], inputResponses={"unrelated": 42}),
    ).json()["result"]
    assert response == initial


@pytest.mark.parametrize("method", ["tools/call", "prompts/get"])
@pytest.mark.parametrize(
    "input_response",
    [
        42,
        {"action": "unknown"},
        {"action": "decline", "content": {"nickname": "ignored"}},
        {"action": "accept"},
        {"action": "accept", "content": None},
        {"action": "accept", "content": {"nickname": 42}},
        {"action": "accept", "content": {"nested": {"object": True}}},
    ],
)
def test_malformed_or_schema_invalid_response_is_rejected(
    method: str,
    input_response: object,
) -> None:
    client = MCPTestClient(create_server().app)
    initial = client.post("/mcp", json=_body(method)).json()["result"]
    response = client.post(
        "/mcp",
        json=_body(
            method,
            requestState=initial["requestState"],
            inputResponses={"profile": input_response},
        ),
    ).json()
    assert response["error"]["code"] == ErrorCode.INVALID_PARAMS
    assert response["error"]["message"] == "Invalid continuation input"
    assert "result" not in response


@pytest.mark.parametrize("method", ["tools/call", "prompts/get"])
def test_tampered_state_is_protocol_failure(method: str) -> None:
    client = MCPTestClient(create_server().app)
    initial = client.post("/mcp", json=_body(method)).json()["result"]
    response = client.post(
        "/mcp",
        json=_body(
            method,
            requestState=initial["requestState"] + "x",
            inputResponses={"profile": {"action": "accept", "content": {"nickname": "Ada"}}},
        ),
    ).json()
    assert response["error"]["code"] == ErrorCode.INVALID_PARAMS


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requestState", 1),
        ("requestState", False),
        ("requestState", None),
        ("inputResponses", []),
        ("inputResponses", "invalid"),
    ],
)
def test_invalid_continuation_parameter_types(field: str, value: object) -> None:
    response = (
        MCPTestClient(create_server().app)
        .post("/mcp", json=_body("tools/call", **{field: value}))
        .json()
    )
    assert response["error"]["code"] == ErrorCode.INVALID_PARAMS


def url_tool() -> InputRequired:
    return InputRequired(
        input_requests={
            "connect": ElicitationRequest(
                params=UrlElicitation(
                    message="Connect your account",
                    url="https://EXAMPLE.com:443/connect%2Faccount",
                ),
            ),
        },
    )


def retry_tool() -> RetryRequired:
    return RetryRequired(request_state="opaque-application-state")


@pytest.mark.parametrize("mode", ["url", "form", "both"])
def test_url_mode_requires_explicit_support(mode: str) -> None:
    server = MCPServer(
        name="test",
        version="1",
        tools=(Tool(func=url_tool, inputs=type(None), output=Greeting),),
    )
    modes: dict[str, dict] = {"url": {}, "form": {}} if mode == "both" else {mode: {}}
    body = _body()
    body["params"].update(name="url_tool", _meta=request_meta(capabilities={"elicitation": modes}))
    response = MCPTestClient(server.app).post("/mcp", json=body)
    if mode == "form":
        assert response.json()["error"]["code"] == ErrorCode.INVALID_PARAMS
    else:
        result = response.json()["result"]
        assert (
            result["inputRequests"]["connect"]["params"]["url"]
            == "https://EXAMPLE.com:443/connect%2Faccount"
        )
        assert "requestState" not in result


def test_state_only_retry_needs_no_client_capabilities() -> None:
    server = MCPServer(
        name="test",
        version="1",
        tools=(Tool(func=retry_tool, inputs=type(None), output=Greeting),),
    )
    body = _body()
    body["params"].update(name="retry_tool", _meta=request_meta())
    response = MCPTestClient(server.app).post("/mcp", json=body).json()
    assert response["result"]["resultType"] == "input_required"
    assert response["result"]["requestState"] == "opaque-application-state"
    assert "inputRequests" not in response["result"]


def test_retry_checks_current_authorization_and_http_headers() -> None:
    scoped = MCPServer(
        name="scoped",
        version="1",
        tools=(Tool(func=greeting, inputs=NoArguments, output=Greeting, scopes=("profile",)),),
    )
    granted = MCPTestClient(mount_mcp_server(scoped, BasicAuthBackend(("profile",))))
    headers = {"Authorization": "Bearer TEST_TOKEN"}
    initial = granted.post("/mcp", json=_body(), headers=headers).json()["result"]
    retry = _body(
        requestState=initial["requestState"],
        inputResponses={"profile": {"action": "accept", "content": {"nickname": "Ada"}}},
    )
    revoked = MCPTestClient(mount_mcp_server(scoped, BasicAuthBackend(())))
    denied = revoked.post("/mcp", json=retry, headers=headers)
    assert denied.status_code == HTTPStatus.FORBIDDEN
    mismatched = granted.post("/mcp", json=retry, headers={**headers, "Mcp-Name": "other"})
    assert mismatched.status_code == HTTPStatus.BAD_REQUEST
    assert mismatched.json()["error"]["code"] == ErrorCode.HEADER_MISMATCH


def test_elicitation_requires_all_modes_and_preserves_multiple_keys() -> None:
    def both_modes() -> InputRequired:
        return InputRequired(
            input_requests={
                "url": ElicitationRequest(
                    params=UrlElicitation(message="Connect", url="https://example.com/connect"),
                ),
                "form": ElicitationRequest(
                    params=FormElicitation(
                        message="Input",
                        requested_schema=ElicitationSchema(properties={"name": StringField()}),
                    ),
                ),
            },
        )

    server = MCPServer(
        name="test",
        version="1",
        tools=(Tool(func=both_modes, inputs=type(None), output=Greeting),),
    )
    body = _body()
    body["params"]["name"] = "both_modes"
    unsupported = MCPTestClient(server.app).post("/mcp", json=body).json()
    assert unsupported["error"]["code"] == ErrorCode.INVALID_PARAMS
    body["params"]["_meta"] = request_meta(capabilities={"elicitation": {"form": {}, "url": {}}})
    supported = MCPTestClient(server.app).post("/mcp", json=body).json()["result"]
    assert set(supported["inputRequests"]) == {"url", "form"}


@pytest.mark.parametrize(
    ("capabilities", "expected"),
    [
        ({}, ""),
        ({"elicitation": {}}, "form"),
        ({"elicitation": {"url": {}}}, "url"),
        ({"elicitation": {"form": {}, "url": {}}}, "form,url"),
        ({"elicitation": {"form": False}}, ""),
    ],
)
def test_invocation_context_exposes_each_requests_modes(capabilities: dict, expected: str) -> None:
    def available_modes(args: Arguments[NoArguments]) -> InvocationResult[Greeting]:
        context = args.continuation
        assert context is not None
        return Greeting(message=",".join(sorted(context.elicitation_modes)))

    server = MCPServer(
        name="test",
        version="1",
        tools=(Tool(func=available_modes, inputs=NoArguments, output=Greeting),),
    )
    body = _body()
    body["params"].update(name="available_modes", _meta=request_meta(capabilities=capabilities))
    result = MCPTestClient(server.app).post("/mcp", json=body).json()["result"]
    assert result["structuredContent"]["message"] == expected


def test_direct_calls_have_no_transport_context() -> None:
    request = Request({"type": "http"})
    assert Arguments(request, NoArguments()).continuation is None


def test_input_required_must_request_something() -> None:
    with pytest.raises(ValidationError):
        InputRequired(input_requests={})


@pytest.mark.parametrize(
    "url",
    ["not a url", "https://example.com/path with spaces", "https://example.com/\n"],
)
def test_invalid_elicitation_url_is_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        UrlElicitation(message="Connect", url=url)


def test_nested_form_schemas_are_rejected() -> None:
    with pytest.raises(ValidationError):
        FormElicitation.model_validate(
            {
                "message": "Nested input",
                "requestedSchema": {
                    "type": "object",
                    "properties": {"nested": {"type": "object", "properties": {}}},
                },
            },
        )


def test_unknown_required_form_property_is_rejected() -> None:
    with pytest.raises(ValidationError):
        FormElicitation.model_validate(
            {
                "message": "Input",
                "requestedSchema": {"type": "object", "properties": {}, "required": ["missing"]},
            },
        )


def test_accepted_response_preserves_scalar_identity() -> None:
    response = AcceptedElicitation(
        content={"boolean": True, "integer": 2, "number": 1.5, "text": "2", "choices": ["a"]},
    )
    assert response.model_dump()["content"] == {
        "boolean": True,
        "integer": 2,
        "number": 1.5,
        "text": "2",
        "choices": ["a"],
    }
    assert type(response.content["boolean"]) is bool if response.content is not None else False


@pytest.mark.asyncio
async def test_stdio_mrtr_two_independent_requests() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "from tests.fixtures.mrtr import run_stdio; run_stdio()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        async with asyncio.timeout(10):
            process.stdin.write(json.dumps(_body()).encode() + b"\n")
            await process.stdin.drain()
            initial = json.loads(await process.stdout.readline())
            assert initial["result"]["resultType"] == "input_required"
            retry = _body(
                requestState=initial["result"]["requestState"],
                inputResponses={"profile": {"action": "accept", "content": {"nickname": "Ada"}}},
            )
            retry["id"] = "retry"
            process.stdin.write(json.dumps(retry).encode() + b"\n")
            await process.stdin.drain()
            completed = json.loads(await process.stdout.readline())
            assert completed["id"] == "retry"
            assert completed["result"]["structuredContent"] == {"message": "Hello, Ada"}
            process.stdin.close()
            await process.wait()
            assert process.returncode == 0
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
