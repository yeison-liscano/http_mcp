from http import HTTPStatus

from starlette.testclient import TestClient

from server.server import MCPServer
from tests.tools import TOOLS


def test_server_list_tools() -> None:
    server = MCPServer(tools=TOOLS, name="test", version="1.0.0", context=None)
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
            "meta": None,
        },
    }


def test_server_call_tool() -> None:
    server = MCPServer(tools=TOOLS, name="test", version="1.0.0", context=None)
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
                    "annotations": None,
                    "meta": None,
                }
            ],
            "structuredContent": {"answer": "Hello, What is the meaning of life?!"},
            "isError": False,
            "meta": None,
        },
    }
