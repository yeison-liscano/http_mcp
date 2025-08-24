from http import HTTPStatus

from starlette.testclient import TestClient

from http_mcp.server import MCPServer
from http_mcp.types import Arguments, Tool
from tests.app.context import Context
from tests.app.main import mount_mcp_server
from tests.models import TestToolArguments, TestToolOutput


async def simple_server_tool_with_context(
    args: Arguments[TestToolArguments],
) -> TestToolOutput:
    """Return a simple server tool with context."""
    assert args.inputs.question == "What is the meaning of life?"
    assert args.request.method == "POST"
    assert args.request.headers.get("Authorization") == "Bearer TEST_TOKEN"
    context = args.get_state_key("context", Context)
    assert context.called_tools == []
    context.add_called_tool("simple_server_tool_with_context")
    return TestToolOutput(answer=f"Hello, {args.inputs.question}!")


TOOLS_SIMPLE_SERVER_WITH_CONTEXT = (
    Tool(
        func=simple_server_tool_with_context,
        inputs=TestToolArguments,
        output=TestToolOutput,
    ),
)


def test_server_call_tool() -> None:
    server = MCPServer(
        tools=TOOLS_SIMPLE_SERVER_WITH_CONTEXT,
        name="test",
        version="1.0.0",
    )
    app = mount_mcp_server(server)
    with TestClient(app, headers={"Authorization": "Bearer TEST_TOKEN"}) as client:
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

        assert client.app_state["context"].called_tools == ["simple_server_tool_with_context"]
