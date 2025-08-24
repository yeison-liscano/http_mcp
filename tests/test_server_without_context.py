from http import HTTPStatus

from starlette.testclient import TestClient

from http_mcp.server import MCPServer
from http_mcp.types import Arguments, Tool
from tests.models import TestToolArguments, TestToolOutput


async def simple_server_tool(args: Arguments[TestToolArguments]) -> TestToolOutput:
    """Return a simple server tool."""
    assert args.inputs.question == "What is the meaning of life?"
    assert args.request.method == "POST"
    return TestToolOutput(answer=f"Hello, {args.inputs.question}!")


TOOLS_SIMPLE_SERVER = (
    Tool(
        func=simple_server_tool,
        inputs=TestToolArguments,
        output=TestToolOutput,
    ),
)


def test_server_list_tools() -> None:
    server = MCPServer(tools=TOOLS_SIMPLE_SERVER, name="test", version="1.0.0")
    client = TestClient(server.app)
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})
    assert response.status_code == HTTPStatus.OK
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {
                    "name": "simple_server_tool",
                    "title": "Simple Server Tool",
                    "description": "Return a simple server tool.",
                    "inputSchema": {
                        "title": "simple_server_toolArguments",
                        "type": "object",
                        "properties": {"question": {"title": "Question", "type": "string"}},
                        "required": ["question"],
                    },
                    "outputSchema": {
                        "title": "simple_server_toolOutput",
                        "type": "object",
                        "properties": {"answer": {"title": "Answer", "type": "string"}},
                        "required": ["answer"],
                    },
                    "annotations": {
                        "title": "Simple Server Tool",
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


def test_server_call_tool() -> None:
    server = MCPServer(tools=TOOLS_SIMPLE_SERVER, name="test", version="1.0.0")
    client = TestClient(server.app)
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": "simple_server_tool",
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
