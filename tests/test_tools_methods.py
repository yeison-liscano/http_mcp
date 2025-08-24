from http import HTTPStatus

from pydantic import BaseModel, Field
from starlette.testclient import TestClient

from http_mcp._transport_types import ProtocolErrorCode
from http_mcp.server import MCPServer
from http_mcp.types import Arguments, Tool
from tests.app.context import Context
from tests.app.main import mount_mcp_server


class TestTool1Arguments(BaseModel):
    question: str = Field(description="The question to answer")


class TestTool1Output(BaseModel):
    answer: str = Field(description="The answer to the question")


class TestTool2Arguments(BaseModel):
    user_id: str = Field(description="The user ID to get information about")


class TestTool2Output(BaseModel):
    user_id: str = Field(description="The user ID")
    email: str = Field(description="The email address of the user")


async def tool_1(args: Arguments[TestTool1Arguments]) -> TestTool1Output:
    """Return a simple answer."""
    assert args.inputs.question == "What is the meaning of life?"
    context = args.get_state_key("context", Context)
    assert context.called_tools == []
    context.add_called_tool("tool_1")
    return TestTool1Output(answer=f"Hello, {args.inputs.question}!")


def tool_2(args: Arguments[TestTool2Arguments]) -> TestTool2Output:
    """Return a simple user information."""
    assert args.inputs.user_id == "123"
    context = args.get_state_key("context", Context)
    assert context.called_tools == ["tool_1"]
    context.add_called_tool("tool_2")
    return TestTool2Output(user_id=args.inputs.user_id, email=f"{args.inputs.user_id}@example.com")


def tool_that_raises_error(
    _args: Arguments[TestTool1Arguments],
) -> TestTool1Output:
    """Return a simple answer."""
    raise ValueError


TOOLS = (
    Tool(
        func=tool_1,
        inputs=TestTool1Arguments,
        output=TestTool1Output,
    ),
    Tool(
        func=tool_2,
        inputs=TestTool2Arguments,
        output=TestTool2Output,
    ),
)


def test_list_tools() -> None:
    server = MCPServer(
        tools=TOOLS,
        name="test",
        version="1.0.0",
    )
    app = mount_mcp_server(server)
    client = TestClient(app)
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})
    assert response.status_code == HTTPStatus.OK
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {
                    "name": "tool_1",
                    "title": "Tool 1",
                    "description": "Return a simple answer.",
                    "inputSchema": {
                        "title": "tool_1Arguments",
                        "type": "object",
                        "properties": {
                            "question": {
                                "title": "Question",
                                "type": "string",
                                "description": "The question to answer",
                            },
                        },
                        "required": ["question"],
                    },
                    "outputSchema": {
                        "title": "tool_1Output",
                        "type": "object",
                        "properties": {
                            "answer": {
                                "title": "Answer",
                                "type": "string",
                                "description": "The answer to the question",
                            },
                        },
                        "required": ["answer"],
                    },
                    "annotations": {
                        "title": "Tool 1",
                        "readOnlyHint": False,
                        "destructiveHint": False,
                        "idempotentHint": True,
                        "openWorldHint": True,
                    },
                    "meta": None,
                },
                {
                    "name": "tool_2",
                    "title": "Tool 2",
                    "description": "Return a simple user information.",
                    "inputSchema": {
                        "title": "tool_2Arguments",
                        "type": "object",
                        "properties": {
                            "user_id": {
                                "title": "User Id",
                                "type": "string",
                                "description": "The user ID to get information about",
                            },
                        },
                        "required": ["user_id"],
                    },
                    "outputSchema": {
                        "title": "tool_2Output",
                        "type": "object",
                        "properties": {
                            "user_id": {
                                "title": "User Id",
                                "type": "string",
                                "description": "The user ID",
                            },
                            "email": {
                                "title": "Email",
                                "type": "string",
                                "description": "The email address of the user",
                            },
                        },
                        "required": ["user_id", "email"],
                    },
                    "annotations": {
                        "title": "Tool 2",
                        "readOnlyHint": False,
                        "destructiveHint": False,
                        "idempotentHint": True,
                        "openWorldHint": True,
                    },
                    "meta": None,
                },
            ],
            "nextCursor": "",
        },
    }


def test_server_call_tools() -> None:
    server = MCPServer(
        tools=TOOLS,
        name="test",
        version="1.0.0",
    )
    app = mount_mcp_server(server)
    with TestClient(app) as client:
        response_1 = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {
                    "name": "tool_1",
                    "arguments": {"question": "What is the meaning of life?"},
                },
            },
        )
        assert response_1.status_code == HTTPStatus.OK
        response_json = response_1.json()
        assert response_json == {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": '{"answer":"Hello, What is the meaning of life?!"}',
                    },
                ],
                "structuredContent": {"answer": "Hello, What is the meaning of life?!"},
                "isError": False,
            },
        }
        assert client.app_state["context"].called_tools == ["tool_1"]

        response_2 = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {
                    "name": "tool_2",
                    "arguments": {"user_id": "123"},
                },
            },
        )

        assert response_2.status_code == HTTPStatus.OK
        response_json = response_2.json()
        assert response_json == {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": '{"user_id":"123","email":"123@example.com"}',
                    },
                ],
                "structuredContent": {"user_id": "123", "email": "123@example.com"},
                "isError": False,
            },
        }
        assert client.app_state["context"].called_tools == ["tool_1", "tool_2"]


def test_server_call_tool_with_invalid_arguments() -> None:
    server = MCPServer(
        tools=TOOLS,
        name="test",
        version="1.0.0",
    )
    app = mount_mcp_server(server)
    client = TestClient(app)
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": "tool_1",
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
            "message": "Protocol error: Error validating arguments for tool tool_1: "
            '[{"type":"missing","loc":["question"],"msg":"Field '
            'required","input":{"invalid_field":"What is the meaning of '
            'life?"},"url":"https://errors.pydantic.dev/2.11/v/missing"}]',
        },
    }


def test_server_call_tool_with_error() -> None:
    server = MCPServer(
        tools=(
            Tool(
                func=tool_that_raises_error,
                inputs=TestTool1Arguments,
                output=TestTool1Output,
            ),
        ),
        name="test",
        version="1.0.0",
    )
    client = TestClient(server.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": "tool_that_raises_error",
                "arguments": {"question": "What is the meaning of life?"},
            },
        },
    )
    assert response.status_code == HTTPStatus.OK
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": "Server error: Error calling tool tool_that_raises_error: "
                    "Unknown error",
                },
            ],
            "isError": True,
        },
    }


def test_tool_not_found() -> None:
    server = MCPServer(
        tools=(),
        name="test",
        version="1.0.0",
        prompts=(),
    )
    client = TestClient(server.app)
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {"name": "not_found", "arguments": {}},
        },
    )
    assert response.status_code == HTTPStatus.OK
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": "Server error: Tool not_found not found",
                },
            ],
            "isError": True,
        },
    }
