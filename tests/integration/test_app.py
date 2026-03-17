from http import HTTPStatus

from starlette.testclient import TestClient

from http_mcp.server import MCPServer
from tests.fixtures.main import BasicAuthBackend, mcp_server, mount_mcp_server
from tests.fixtures.prompts import PROMPTS
from tests.fixtures.tools import TOOLS

HEADER_AUTHORIZATION = {"Authorization": "Bearer TEST_TOKEN"}


def server_with_public_tools() -> None:
    server_with_public_tools = MCPServer(
        tools=tuple(tool for tool in TOOLS if not tool.scopes),
        name="test",
        version="1.0.0",
    )
    app = mount_mcp_server(server_with_public_tools)
    client = TestClient(app)
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1,
            "params": {},
        },
    )
    assert response.status_code == HTTPStatus.OK


def test_http_list_only_public_tools() -> None:
    app = mount_mcp_server(mcp_server, BasicAuthBackend())
    client = TestClient(app)
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
                tool.generate_json_schema() # type: ignore[attr-defined]
                for tool in sorted(TOOLS, key=lambda x: x.name) # type: ignore[attr-defined]
                if not tool.scopes # type: ignore[attr-defined]
            ],
        },
    }


def test_public_and_private_tools() -> None:
    app = mount_mcp_server(mcp_server, BasicAuthBackend(("private",)))
    client = TestClient(app, headers=HEADER_AUTHORIZATION)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
    )
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                tool.generate_json_schema() # type: ignore[attr-defined]
                for tool in sorted(TOOLS, key=lambda x: x.name) # type: ignore[attr-defined]
                if (not tool.scopes or tool.scopes == ("private",)) # type: ignore[attr-defined]
            ],
        },
    }


def test_private_and_superuser_tools() -> None:
    app = mount_mcp_server(mcp_server, BasicAuthBackend(("private", "superuser")))
    client = TestClient(app, headers=HEADER_AUTHORIZATION)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
    )
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                tool.generate_json_schema() # type: ignore[attr-defined]
                for tool in sorted(TOOLS, key=lambda x: x.name) # type: ignore[attr-defined]
            ],
        },
    }


def test_public_prompts() -> None:
    app = mount_mcp_server(mcp_server, BasicAuthBackend())
    client = TestClient(app, headers=HEADER_AUTHORIZATION)
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "prompts/list", "id": 1})
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "prompts": [
                prompt.to_prompt_protocol_object().model_dump(mode="json")
                for prompt in PROMPTS
                if not prompt.scopes
            ],
        },
    }


def test_private_prompts() -> None:
    app = mount_mcp_server(mcp_server, BasicAuthBackend(("private",)))
    client = TestClient(app, headers=HEADER_AUTHORIZATION)
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "prompts/list", "id": 1})
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "prompts": [
                prompt.to_prompt_protocol_object().model_dump(mode="json")
                for prompt in PROMPTS
                if prompt.scopes == ("private",) or not prompt.scopes
            ],
        },
    }


def test_private_and_superuser_prompts() -> None:
    app = mount_mcp_server(mcp_server, BasicAuthBackend(("private", "superuser")))
    client = TestClient(app, headers=HEADER_AUTHORIZATION)
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "prompts/list", "id": 1})
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "prompts": [
                prompt.to_prompt_protocol_object().model_dump(mode="json") for prompt in PROMPTS
            ],
        },
    }
