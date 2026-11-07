"""Expected failures are returned, so these tests read the values directly."""

import pytest
from pydantic import BaseModel, ValidationError
from starlette.requests import Request

from http_mcp._json_rcp_types.errors import Error, ErrorCode
from http_mcp._mcp_types.content import TextContent
from http_mcp._mcp_types.meta import Implementation, ResultMeta
from http_mcp._mcp_types.prompts import PromptGetResult, PromptMessage, RenderedPrompt
from http_mcp._mcp_types.results import CacheableResult
from http_mcp._mcp_types.tools import ToolsCallFailure, ToolsCallSuccess
from http_mcp.exceptions import PromptInvocationError, ServerError, ToolInvocationError
from http_mcp.failures import (
    InsufficientScope,
    InvalidArguments,
    PromptInvocationFailed,
    PromptNotFound,
    PromptServerFailure,
    ToolInvocationFailed,
    ToolNotFound,
)
from http_mcp.server import MCPServer
from http_mcp.types import Arguments, Prompt, Tool
from http_mcp.types.models import ErrorMessage

_MAX_NAME_LENGTH = 100
_META = ResultMeta(server_info=Implementation(name="test", version="1.0.0"))


class Inputs(BaseModel):
    count: int


class Output(BaseModel):
    count: int


def echo(args: Arguments[Inputs]) -> Output:
    return Output(count=args.inputs.count)


def fails_as_expected() -> Output:
    raise ToolInvocationError("fails_as_expected", "Value must be positive")


def fails_with_server_error() -> Output:
    raise ServerError(Error(code=ErrorCode.INTERNAL_ERROR, description="State is missing"))


def crashes() -> Output:
    raise RuntimeError


def greet(args: Arguments[Inputs]) -> tuple[PromptMessage, ...]:
    return (PromptMessage(role="user", content=TextContent(text=str(args.inputs.count))),)


def prompt_fails_as_expected() -> tuple[PromptMessage, ...]:
    raise PromptInvocationError("prompt_fails_as_expected", "Nothing to render")


def prompt_fails_with_server_error() -> tuple[PromptMessage, ...]:
    raise ServerError(Error(code=ErrorCode.INTERNAL_ERROR, description="State is missing"))


def prompt_crashes() -> tuple[PromptMessage, ...]:
    raise RuntimeError


@pytest.fixture
def request_stub() -> Request:
    return Request({"type": "http", "method": "POST", "headers": [], "path": "/"})


@pytest.mark.asyncio
async def test_unknown_tool_is_reported_as_a_value(request_stub: Request) -> None:
    outcome = await MCPServer("test", "1.0.0").call_tool("missing", {}, request_stub)

    assert outcome == ToolNotFound("missing")


@pytest.mark.asyncio
async def test_unknown_prompt_is_reported_as_a_value(request_stub: Request) -> None:
    outcome = await MCPServer("test", "1.0.0").get_prompt("missing", {}, request_stub)

    assert outcome == PromptNotFound("missing")


@pytest.mark.parametrize("failure", [ToolNotFound("x" * 500), PromptNotFound("x" * 500)])
def test_not_found_messages_truncate_the_untrusted_name(
    failure: ToolNotFound | PromptNotFound,
) -> None:
    assert "x" * _MAX_NAME_LENGTH in failure.message
    assert "x" * (_MAX_NAME_LENGTH + 1) not in failure.message


def test_invalid_arguments_message_truncates_the_untrusted_name() -> None:
    failure = InvalidArguments("tool", "x" * 500, "details")

    assert failure.message == (
        f"Error validating arguments for tool {'x' * _MAX_NAME_LENGTH}: details"
    )


@pytest.mark.asyncio
async def test_scoped_tool_without_an_auth_backend_is_denied(request_stub: Request) -> None:
    tool = Tool(func=echo, inputs=Inputs, output=Output, scopes=("admin",))

    outcome = await MCPServer("test", "1.0.0", (tool,)).call_tool(
        "echo",
        {"count": 1},
        request_stub,
    )

    assert outcome == InsufficientScope(("admin",))


@pytest.mark.asyncio
async def test_scoped_prompt_without_an_auth_backend_is_denied(request_stub: Request) -> None:
    prompt = Prompt(func=greet, arguments_type=Inputs, scopes=("admin",))

    outcome = await MCPServer("test", "1.0.0", prompts=(prompt,)).get_prompt(
        "greet",
        {"count": 1},
        request_stub,
    )

    assert outcome == InsufficientScope(("admin",))


@pytest.mark.asyncio
async def test_tool_arguments_failing_validation_are_a_value(request_stub: Request) -> None:
    tool = Tool(func=echo, inputs=Inputs, output=Output)

    match await tool.invoke({"count": "nope"}, request_stub):
        case InvalidArguments(feature_type=feature_type, name=name):
            assert (feature_type, name) == ("tool", "echo")
        case other:
            pytest.fail(f"unexpected outcome: {other!r}")


@pytest.mark.asyncio
async def test_prompt_arguments_failing_validation_are_a_value(request_stub: Request) -> None:
    prompt = Prompt(func=greet, arguments_type=Inputs)

    match await prompt.invoke({"count": "nope"}, request_stub):
        case InvalidArguments(feature_type=feature_type, name=name):
            assert (feature_type, name) == ("prompt", "greet")
        case other:
            pytest.fail(f"unexpected outcome: {other!r}")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("func", "expected"),
    [
        pytest.param(
            fails_as_expected,
            ToolInvocationFailed("Error calling tool fails_as_expected: Value must be positive"),
            id="tool-invocation-error",
        ),
        pytest.param(
            fails_with_server_error,
            ToolInvocationFailed("State is missing"),
            id="server-error",
        ),
        pytest.param(
            crashes,
            ToolInvocationFailed("Error calling tool crashes: Unknown error"),
            id="crash-hides-the-details",
        ),
    ],
)
async def test_exceptions_from_tool_functions_stop_at_the_tool(
    func: object,
    expected: ToolInvocationFailed,
    request_stub: Request,
) -> None:
    tool: Tool = Tool(func=func, inputs=type(None), output=Output)  # type: ignore[arg-type]

    assert await tool.invoke({}, request_stub) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("func", "expected"),
    [
        pytest.param(
            fails_as_expected,
            ErrorMessage(
                error_message="Error calling tool fails_as_expected: Value must be positive",
            ),
            id="tool-invocation-error",
        ),
        pytest.param(
            fails_with_server_error,
            ToolInvocationFailed("State is missing"),
            id="server-error-is-not-converted",
        ),
        pytest.param(
            crashes,
            ErrorMessage(error_message="Error calling tool crashes: Unknown error"),
            id="crash-hides-the-details",
        ),
    ],
)
async def test_return_error_message_only_covers_invocation_failures(
    func: object,
    expected: ErrorMessage | ToolInvocationFailed,
    request_stub: Request,
) -> None:
    tool: Tool = Tool(
        func=func,  # type: ignore[arg-type]
        inputs=type(None),
        output=Output,
        return_error_message=True,
    )

    assert await tool.invoke({}, request_stub) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("func", "expected"),
    [
        pytest.param(
            prompt_fails_as_expected,
            PromptInvocationFailed(
                "Error getting prompt prompt_fails_as_expected: Nothing to render",
            ),
            id="prompt-invocation-error",
        ),
        pytest.param(
            prompt_fails_with_server_error,
            PromptServerFailure(ErrorCode.INTERNAL_ERROR, "State is missing"),
            id="server-error",
        ),
        pytest.param(
            prompt_crashes,
            PromptInvocationFailed("Error getting prompt prompt_crashes: Unknown error"),
            id="crash-hides-the-details",
        ),
    ],
)
async def test_exceptions_from_prompt_functions_stop_at_the_prompt(
    func: object,
    expected: PromptInvocationFailed | PromptServerFailure,
    request_stub: Request,
) -> None:
    prompt: Prompt = Prompt(func=func, arguments_type=type(None))  # type: ignore[arg-type]

    assert await prompt.invoke({}, request_stub) == expected


@pytest.mark.asyncio
async def test_successful_prompt_carries_its_description(request_stub: Request) -> None:
    prompt = Prompt(func=greet, arguments_type=Inputs)

    match await prompt.invoke({"count": 1}, request_stub):
        case RenderedPrompt(description=description, messages=messages):
            assert description == prompt.description
            assert len(messages) == 1
        case other:
            pytest.fail(f"unexpected outcome: {other!r}")


def test_a_result_without_server_metadata_cannot_be_built() -> None:
    with pytest.raises(ValidationError):
        PromptGetResult(description="d", messages=())  # type: ignore[call-arg]


def test_a_cacheable_result_without_caching_hints_cannot_be_built() -> None:
    with pytest.raises(ValidationError):
        CacheableResult(meta=_META)  # type: ignore[call-arg]


def test_a_successful_tool_result_requires_structured_content() -> None:
    with pytest.raises(ValidationError):
        ToolsCallSuccess(meta=_META, content=())  # type: ignore[call-arg]


def test_a_failed_tool_result_cannot_claim_success() -> None:
    with pytest.raises(ValidationError):
        ToolsCallFailure(meta=_META, content=(), is_error=False)  # type: ignore[arg-type]
