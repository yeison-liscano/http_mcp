from dataclasses import dataclass, field
from http import HTTPStatus

from starlette.testclient import TestClient

from http_mcp.server import MCPServer
from http_mcp.tools import Tool, ToolArguments
from tests.models import TestToolArguments, TestToolOutput


@dataclass
class Context:
    called_tools: list[str] = field(default_factory=list)

    def get_called_tools(self) -> list[str]:
        return self.called_tools

    def add_called_tool(self, tool_name: str) -> None:
        self.called_tools.append(tool_name)

async def simple_server_tool_with_context(
    args: ToolArguments[TestToolArguments, Context],
) -> TestToolOutput:
    """Return a simple server tool with context."""
    assert args.inputs.question == "What is the meaning of life?"
    assert args.request.method == "POST"
    assert args.request.headers.get("Authorization") == "Bearer TEST_TOKEN"
    assert args.context.called_tools == []
    args.context.add_called_tool("simple_server_tool_with_context")
    return TestToolOutput(answer=f"Hello, {args.inputs.question}!")


TOOLS_SIMPLE_SERVER_WITH_CONTEXT = (
    Tool(
        func=simple_server_tool_with_context,
        input=TestToolArguments,
        output=TestToolOutput,
    ),
)


def test_server_call_tool() -> None:
    context = Context(called_tools=[])
    server = MCPServer(
        tools=TOOLS_SIMPLE_SERVER_WITH_CONTEXT,
        name="test",
        version="1.0.0",
        context=context,
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
                },
            ],
            "structuredContent": {"answer": "Hello, What is the meaning of life?!"},
            "isError": False,
        },
    }

    assert context.called_tools == ["simple_server_tool_with_context"]
