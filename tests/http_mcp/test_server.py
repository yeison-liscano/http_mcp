from http import HTTPStatus

from starlette.testclient import TestClient

from http_mcp._json_rcp_types.errors import ErrorCode
from http_mcp.server import MCPServer
from http_mcp.types import Arguments, Tool
from tests.fixtures.context import Context
from tests.fixtures.main import BasicAuthBackend, mount_mcp_server
from tests.fixtures.models import TestToolArguments, TestToolOutput

# ---------------------------------------------------------------------------
# Helper tools used across the merged test modules
# ---------------------------------------------------------------------------


async def initialization_test_tool(args: Arguments[TestToolArguments]) -> TestToolOutput:
    """Test tool for initialization testing."""
    return TestToolOutput(answer=f"Initialized with: {args.inputs.question}")


TOOLS_INITIALIZATION = (
    Tool(
        func=initialization_test_tool,
        inputs=TestToolArguments,
        output=TestToolOutput,
    ),
)


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
    assert context.called_tools == ["simple_server_tool_with_context"]
    return TestToolOutput(answer=f"Hello, {args.inputs.question}!")


TOOLS_SIMPLE_SERVER_WITH_CONTEXT = (
    Tool(
        func=simple_server_tool_with_context,
        inputs=TestToolArguments,
        output=TestToolOutput,
    ),
)

TOOLS_SIMPLE_SERVER_WITH_SCOPES = (
    Tool(
        func=simple_server_tool_with_context,
        inputs=TestToolArguments,
        output=TestToolOutput,
        scopes=("private",),
    ),
)


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


# ---------------------------------------------------------------------------
# Tests from test_initialization.py
# ---------------------------------------------------------------------------


def test_server_capabilities_with_tools() -> None:
    server = MCPServer(
        tools=TOOLS_INITIALIZATION,
        name="capabilities_test",
        version="1.0.0",
    )

    capabilities = server.capabilities
    assert capabilities.tools is not None
    assert capabilities.tools.list_changed is False
    assert capabilities.tools.subscribe is False
    assert capabilities.prompts is None


def test_protocol_initialization() -> None:
    server = MCPServer(
        tools=TOOLS_INITIALIZATION,
        name="protocol_test_initialization",
        version="1.0.2",
    )
    client = TestClient(server.app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"roots": {"listChanged": True}, "sampling": {}, "elicitation": {}},
                "clientInfo": {
                    "name": "ExampleClient",
                    "title": "Example Client Display Name",
                    "version": "1.0.0",
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
            "protocolVersion": "2025-06-18",
            "capabilities": {
                "tools": {"listChanged": False, "subscribe": False},
            },
            "serverInfo": {
                "name": "protocol_test_initialization",
                "version": "1.0.2",
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests from test_server_with_context.py
# ---------------------------------------------------------------------------


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


def test_server_call_tool_with_scope() -> None:
    server = MCPServer(
        tools=TOOLS_SIMPLE_SERVER_WITH_SCOPES,
        name="test",
        version="1.0.0",
    )
    app = mount_mcp_server(server, BasicAuthBackend(("private",)))
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


def test_server_call_tool_without_required_scope() -> None:
    server = MCPServer(
        tools=TOOLS_SIMPLE_SERVER_WITH_SCOPES,
        name="test",
        version="1.0.0",
    )
    app = mount_mcp_server(server, BasicAuthBackend(("no_sufficient_scope",)))
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
            "error": {
                "code": ErrorCode.RESOURCE_NOT_FOUND.value,
                "message": "Tool simple_server_tool_with_context not found",
            },
        }

        assert client.app_state["context"].called_tools == []


# ---------------------------------------------------------------------------
# Tests from test_server_without_context.py
# ---------------------------------------------------------------------------


def test_server_list_tools() -> None:
    server = MCPServer(tools=TOOLS_SIMPLE_SERVER, name="test", version="1.0.0")
    client = TestClient(server.app)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
    )
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
        },
    }


def test_server_call_tool_without_context() -> None:
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
