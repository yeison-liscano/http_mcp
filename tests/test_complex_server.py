from http import HTTPStatus

from starlette.testclient import TestClient

from app.tools import Context
from server.models import Input, Tool
from server.server import MCPServer
from tests.models import TestToolArguments, TestToolOutput


async def simple_server_tool_with_context(
    args: Input[TestToolArguments, Context],
) -> TestToolOutput:
    """Return a simple server tool with context."""
    assert args.arguments.question == "What is the meaning of life?"
    assert args.request.method == "POST"
    assert args.request.headers.get("Authorization") == "Bearer TEST_TOKEN"
    assert args.context.called_tools == ["mock_tool"]
    return TestToolOutput(answer=f"Hello, {args.arguments.question}!")


TOOLS_SIMPLE_SERVER_WITH_CONTEXT = (
    Tool(
        func=simple_server_tool_with_context,
        input=Input[TestToolArguments, Context],
        input_arguments=TestToolArguments,
        output=TestToolOutput,
    ),
)


def test_server_call_tool() -> None:
    server = MCPServer(
        tools=TOOLS_SIMPLE_SERVER_WITH_CONTEXT,
        name="test",
        version="1.0.0",
        context=Context(called_tools=["mock_tool"]),
    )
    client = TestClient(server.app, headers={"Authorization": "Bearer TEST_TOKEN"})
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": "simple_server_tool_with_context",
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
                    "text": '{"answer":"Hello, What is the meaning of life?!"}',
                    "annotations": None,
                    "meta": None,
                }
            ],
            "structuredContent": {"answer": "Hello, What is the meaning of life?!"},
            "isError": False,
            "meta": None,
        },
    }
