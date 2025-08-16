from http import HTTPStatus

from pydantic import BaseModel, Field
from starlette.testclient import TestClient

from server.content import TextContent
from server.prompts import Prompt, PromptMessage
from server.server import MCPServer


class TestArguments(BaseModel):
    argument_1: int = Field(description="The first argument")
    argument_2: str = Field(description="The second argument")
    argument_3: bool = Field(description="The third argument", default=True)
    argument_4: float = Field(description="The fourth argument", default=1.0)


def prompt_1(arg: TestArguments) -> tuple[PromptMessage, ...]:
    """Test prompt."""
    return (PromptMessage(role="user", content=TextContent(text=arg.model_dump_json())),)


PROMPT = Prompt(
    func=prompt_1,
    arguments_type=TestArguments,
)


def test_prompt_list() -> None:
    server = MCPServer[None]( # type: ignore [misc]
        tools=(),
        name="test",
        version="1.0.0",
        prompts=(PROMPT,),
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
                    "description": "Test prompt.",
                    "name": "prompt_1",
                    "title": "Prompt 1",
                },
            ],
        },
    }


def test_prompt_get() -> None:
    server = MCPServer[None](  # type: ignore [misc]
        tools=(),
        name="test",
        version="1.0.0",
        prompts=(PROMPT,),
    )
    client = TestClient(server.app, headers={"Authorization": "Bearer TEST_TOKEN"})
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "prompts/get",
            "id": 1,
            "params": {
                "name": "prompt_1",
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
            "description": "Test prompt.",
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


def test_prompts() -> None:
    class TestArguments2(BaseModel):
        argument_1: int = Field(description="The first argument")
        argument_2: str = Field(description="The second argument")

    def prompt_2(arg: TestArguments2) -> tuple[PromptMessage, ...]:
        """Test prompt."""
        return (PromptMessage(role="user", content=TextContent(text=arg.model_dump_json())),)

    prompt = Prompt(
        func=prompt_2,
        arguments_type=TestArguments2,
    )
    server = MCPServer[None]( # type: ignore [misc]
        tools=(),
        name="test",
        version="1.0.0",
        prompts=(PROMPT, prompt),
    )

    client = TestClient(server.app, headers={"Authorization": "Bearer TEST_TOKEN"})
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "prompts/get",
            "id": 1,
            "params": {
                "name": "prompt_1",
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
            "description": "Test prompt.",
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
