from http import HTTPStatus

import pytest
from pydantic import BaseModel, Field
from starlette.testclient import TestClient

from http_mcp._transport_types import ProtocolErrorCode
from http_mcp.mcp_types.content import TextContent
from http_mcp.mcp_types.prompts import PromptMessage
from http_mcp.server import MCPServer
from http_mcp.types import Arguments, Prompt


class TestArguments(BaseModel):
    argument_1: int = Field(description="The first argument")
    argument_2: str = Field(description="The second argument")
    argument_3: bool = Field(description="The third argument", default=True)
    argument_4: float = Field(description="The fourth argument", default=1.0)


def prompt_sync(arg: Arguments[TestArguments]) -> tuple[PromptMessage, ...]:
    """Test prompt sync."""
    return (PromptMessage(role="user", content=TextContent(text=arg.inputs.model_dump_json())),)


async def prompt_async(arg: Arguments[TestArguments]) -> tuple[PromptMessage, ...]:
    """Test prompt async."""
    return (PromptMessage(role="user", content=TextContent(text=arg.inputs.model_dump_json())),)


def prompt_that_raises_error(_arg: Arguments[TestArguments]) -> tuple[PromptMessage, ...]:
    """Test prompt that raises an error."""
    raise ValueError


PROMPT_SYNC = Prompt(
    func=prompt_sync,
    arguments_type=TestArguments,
)

PROMPT_ASYNC = Prompt(
    func=prompt_async,
    arguments_type=TestArguments,
)


PROMPT_ERROR = Prompt(
    func=prompt_that_raises_error,
    arguments_type=TestArguments,
)


@pytest.mark.parametrize("prompt", [PROMPT_SYNC, PROMPT_ASYNC])
def test_prompt_list(prompt: Prompt) -> None:
    server = MCPServer(
        tools=(),
        name="test",
        version="1.0.0",
        prompts=(prompt,),
    )
    client = TestClient(server.app, headers={"Authorization": "Bearer TEST_TOKEN"})
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "prompts/list", "id": 1})
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "prompts": [
                {
                    "arguments": [
                        {
                            "description": "The first argument",
                            "name": "argument_1",
                            "required": True,
                        },
                        {
                            "description": "The second argument",
                            "name": "argument_2",
                            "required": True,
                        },
                        {
                            "description": "The third argument",
                            "name": "argument_3",
                            "required": False,
                        },
                        {
                            "description": "The fourth argument",
                            "name": "argument_4",
                            "required": False,
                        },
                    ],
                    "description": prompt.description,
                    "name": prompt.name,
                    "title": prompt.title,
                },
            ],
        },
    }


@pytest.mark.parametrize("prompt", [PROMPT_SYNC, PROMPT_ASYNC])
def test_prompt_get(prompt: Prompt) -> None:
    server = MCPServer(
        tools=(),
        name="test",
        version="1.0.0",
        prompts=(prompt,),
    )
    client = TestClient(server.app, headers={"Authorization": "Bearer TEST_TOKEN"})
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "prompts/get",
            "id": 1,
            "params": {
                "name": prompt.name,
                "arguments": {
                    "argument_1": 1,
                    "argument_2": "test",
                    "argument_3": False,
                    "argument_4": 2.0,
                },
            },
        },
    )

    assert response.status_code == HTTPStatus.OK
    response_json = response.json()
    assert response_json == {
        "id": 1,
        "jsonrpc": "2.0",
        "result": {
            "description": prompt.description,
            "messages": [
                {
                    "content": {
                        "text": (
                            '{"argument_1":1,"argument_2":"test","argument_3":false,"argument_4":2.0}'
                        ),
                        "type": "text",
                    },
                    "role": "user",
                },
            ],
        },
    }


@pytest.mark.parametrize("prompt", [PROMPT_SYNC, PROMPT_ASYNC])
def test_prompts(
    prompt: Prompt,
) -> None:
    server = MCPServer(
        tools=(),
        name="test",
        version="1.0.0",
        prompts=(prompt,),
    )

    client = TestClient(server.app, headers={"Authorization": "Bearer TEST_TOKEN"})
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "prompts/get",
            "id": 1,
            "params": {
                "name": prompt.name,
                "arguments": {
                    "argument_1": 1,
                    "argument_2": "test",
                    "argument_3": False,
                    "argument_4": 2.0,
                },
            },
        },
    )

    assert response.status_code == HTTPStatus.OK
    response_json = response.json()
    assert response_json == {
        "id": 1,
        "jsonrpc": "2.0",
        "result": {
            "description": prompt.description,
            "messages": [
                {
                    "content": {
                        "text": (
                            '{"argument_1":1,"argument_2":"test","argument_3":false,"argument_4":2.0}'
                        ),
                        "type": "text",
                    },
                    "role": "user",
                },
            ],
        },
    }


@pytest.mark.parametrize("prompt", [PROMPT_SYNC, PROMPT_ASYNC])
def test_server_call_prompt_with_invalid_arguments(prompt: Prompt) -> None:
    server = MCPServer(
        tools=(),
        name="test",
        version="1.0.0",
        prompts=(prompt,),
    )
    client = TestClient(server.app, headers={"Authorization": "Bearer TEST_TOKEN"})
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "prompts/get",
            "id": 1,
            "params": {
                "name": prompt.name,
                "arguments": {"invalid_field": "What is the meaning of life?"},
            },
        },
    )
    assert response.status_code == HTTPStatus.OK
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": ProtocolErrorCode.INVALID_PARAMS.value,
            "message": f"Protocol error: Error validating arguments for prompt {prompt.name}: "
            '[{"type":"missing","loc":["argument_1"],"msg":"Field '
            'required","input":{"invalid_field":"What is the meaning of '
            'life?"},"url":"https://errors.pydantic.dev/2.11/v/missing"},{"type":"missing","loc":'
            '["argument_2"],"msg":"Field '
            'required","input":{"invalid_field":"What is the meaning of '
            'life?"},"url":"https://errors.pydantic.dev/2.11/v/missing"}]',
        },
    }


def test_server_call_prompt_with_error() -> None:
    server = MCPServer(
        tools=(),
        name="test",
        version="1.0.0",
        prompts=(PROMPT_ERROR,),
    )
    client = TestClient(server.app, headers={"Authorization": "Bearer TEST_TOKEN"})
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "prompts/get",
            "id": 1,
            "params": {
                "name": PROMPT_ERROR.name,
                "arguments": {
                    "argument_1": 1,
                    "argument_2": "test",
                    "argument_3": False,
                    "argument_4": 2.0,
                },
            },
        },
    )
    assert response.status_code == HTTPStatus.OK
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "description": "Server error: Error getting prompt prompt_that_raises_error: "
            "Unknown error",
            "messages": [],
        },
    }


def test_prompt_not_found() -> None:
    server = MCPServer(
        tools=(),
        name="test",
        version="1.0.0",
        prompts=(),
    )
    client = TestClient(server.app, headers={"Authorization": "Bearer TEST_TOKEN"})
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "prompts/get",
            "id": 1,
            "params": {
                "name": "not_found",
                "arguments": {},
            },
        },
    )
    assert response.status_code == HTTPStatus.OK
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "description": "Server error: Prompt not_found not found",
            "messages": [],
        },
    }
