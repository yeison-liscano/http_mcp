from http import HTTPStatus

from starlette.testclient import TestClient

from auth_mcp.resource_server.integration import ProtectedMCPAppConfig, create_protected_mcp_app
from auth_mcp.resource_server.token_validator import TokenInfo, TokenValidator
from http_mcp.server import MCPServer
from http_mcp.types import Tool
from http_mcp.types.models import NoArguments

_VALID_TOKEN = "valid_token"  # noqa: S105
_PUBLIC_ONLY_TOKEN = "public_only_token"  # noqa: S105


class MockTokenValidator(TokenValidator):
    async def validate_token(
        self,
        token: str,
        _resource: str | None = None,
    ) -> TokenInfo | None:
        if token == _VALID_TOKEN:
            return TokenInfo(
                subject="testuser@example.com",
                scopes=("read", "private"),
                client_id="test_client",
            )
        if token == _PUBLIC_ONLY_TOKEN:
            return TokenInfo(
                subject="publicuser@example.com",
                scopes=("read",),
                client_id="test_client",
            )
        return None


def _get_weather() -> NoArguments:
    """Get the current weather."""
    return NoArguments()


def _private_tool() -> NoArguments:
    """Private tool requiring scope."""
    return NoArguments()


_TOOLS = (
    Tool(func=_get_weather, inputs=type(None), output=NoArguments),
    Tool(
        func=_private_tool,
        inputs=type(None),
        output=NoArguments,
        scopes=("private",),
    ),
)


def _create_app(*, require_authentication: bool = True) -> TestClient:
    server = MCPServer(
        name="test-auth",
        version="1.0.0",
        tools=_TOOLS,
    )
    config = ProtectedMCPAppConfig(
        mcp_server=server,
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        authorization_servers=("https://auth.example.com",),
        scopes_supported=("read", "write", "private"),
        require_authentication=require_authentication,
    )
    app = create_protected_mcp_app(config)
    return TestClient(app)


def test_protected_resource_metadata_endpoint() -> None:
    client = _create_app(require_authentication=False)
    response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["resource"] == "https://mcp.example.com/"
    assert data["scopes_supported"] == ["read", "write", "private"]


def test_unauthenticated_request_sees_public_tools() -> None:
    client = _create_app(require_authentication=False)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
    )
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    tool_names = [t["name"] for t in data["result"]["tools"]]
    assert "_get_weather" in tool_names
    assert "_private_tool" not in tool_names


def test_unauthenticated_request_returns_401_when_auth_required() -> None:
    client = _create_app(require_authentication=True)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert "www-authenticate" in response.headers
    www_auth = response.headers["www-authenticate"]
    assert "Bearer" in www_auth
    assert "resource_metadata=" in www_auth


def test_authenticated_request_lists_all_accessible_tools() -> None:
    client = _create_app(require_authentication=True)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
        headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
    )
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    tool_names = [t["name"] for t in data["result"]["tools"]]
    assert "_get_weather" in tool_names
    assert "_private_tool" in tool_names


def test_public_only_token_sees_only_public_tools() -> None:
    client = _create_app(require_authentication=False)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
        headers={"Authorization": f"Bearer {_PUBLIC_ONLY_TOKEN}"},
    )
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    tool_names = [t["name"] for t in data["result"]["tools"]]
    assert "_get_weather" in tool_names
    assert "_private_tool" not in tool_names


def test_invalid_token_returns_401_when_auth_required() -> None:
    client = _create_app(require_authentication=True)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
        headers={"Authorization": "Bearer bad_token"},
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert "www-authenticate" in response.headers


def test_invalid_token_sees_public_tools_when_auth_not_required() -> None:
    client = _create_app(require_authentication=False)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
        headers={"Authorization": "Bearer bad_token"},
    )
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    tool_names = [t["name"] for t in data["result"]["tools"]]
    assert "_get_weather" in tool_names
    assert "_private_tool" not in tool_names


def test_default_require_authentication_is_true() -> None:
    client = _create_app()
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED
