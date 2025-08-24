from http import HTTPStatus

from starlette.testclient import TestClient

from http_mcp.server import MCPServer
from http_mcp.types import Arguments, Tool
from tests.models import TestToolArguments, TestToolOutput


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
