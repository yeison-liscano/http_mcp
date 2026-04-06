from http import HTTPStatus

from starlette.testclient import TestClient

from auth_mcp.authorization_server.client_store import ClientStore
from auth_mcp.resource_server.integration import (
    CORSConfig,
    ProtectedMCPAppConfig,
    create_protected_mcp_app,
)
from auth_mcp.resource_server.token_validator import TokenInfo, TokenValidator
from auth_mcp.types.metadata import AuthorizationServerMetadata
from auth_mcp.types.registration import ClientRegistrationRequest, ClientRegistrationResponse
from http_mcp.server import MCPServer
from http_mcp.types import Tool
from http_mcp.types.models import NoArguments

_VALID_TOKEN = "valid_token"  # noqa: S105
_PUBLIC_ONLY_TOKEN = "public_only_token"  # noqa: S105

_AS_METADATA = AuthorizationServerMetadata(
    issuer="https://auth.example.com",
    authorization_endpoint="https://auth.example.com/authorize",
    token_endpoint="https://auth.example.com/token",  # noqa: S106
    registration_endpoint="https://auth.example.com/register",
)


class MockClientStore(ClientStore):
    def __init__(self) -> None:
        self._counter = 0

    async def register_client(
        self,
        request: ClientRegistrationRequest,
    ) -> ClientRegistrationResponse:
        self._counter += 1
        return ClientRegistrationResponse(
            client_id=f"client_{self._counter}",
            redirect_uris=request.redirect_uris,
            grant_types=request.grant_types,
            response_types=request.response_types,
            token_endpoint_auth_method=request.token_endpoint_auth_method,
        )


class MockTokenValidator(TokenValidator):
    async def validate_token(
        self,
        token: str,
        resource: str | None = None,
    ) -> TokenInfo | None:
        if token == _VALID_TOKEN:
            return TokenInfo(
                subject="testuser@example.com",
                scopes=("read", "private"),
                client_id="test_client",
                audience=resource,
            )
        if token == _PUBLIC_ONLY_TOKEN:
            return TokenInfo(
                subject="publicuser@example.com",
                scopes=("read",),
                client_id="test_client",
                audience=resource,
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
    response = client.get("/.well-known/oauth-protected-resource/mcp")
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
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "max-age=" in response.headers["strict-transport-security"]


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


def test_cors_config_adds_cors_headers() -> None:
    server = MCPServer(
        name="test-cors",
        version="1.0.0",
        tools=_TOOLS,
    )
    config = ProtectedMCPAppConfig(
        mcp_server=server,
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        authorization_servers=("https://auth.example.com",),
        require_authentication=False,
        cors=CORSConfig(
            allow_origins=("https://client.example.com",),
        ),
    )
    app = create_protected_mcp_app(config)
    client = TestClient(app)
    response = client.options(
        "/mcp",
        headers={
            "Origin": "https://client.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert "access-control-allow-origin" in response.headers
    assert response.headers["access-control-allow-origin"] == "https://client.example.com"


def test_authorization_server_metadata_endpoint() -> None:
    server = MCPServer(name="test-as", version="1.0.0", tools=_TOOLS)
    config = ProtectedMCPAppConfig(
        mcp_server=server,
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        authorization_servers=("https://auth.example.com",),
        require_authentication=False,
        authorization_server_metadata=_AS_METADATA,
    )
    app = create_protected_mcp_app(config)
    client = TestClient(app)
    response = client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["issuer"] == "https://auth.example.com/"
    assert data["authorization_endpoint"] == "https://auth.example.com/authorize"
    assert data["token_endpoint"] == "https://auth.example.com/token"  # noqa: S105


def test_client_store_serves_register_endpoint() -> None:
    server = MCPServer(name="test-dcr", version="1.0.0", tools=_TOOLS)
    config = ProtectedMCPAppConfig(
        mcp_server=server,
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        authorization_servers=("https://auth.example.com",),
        require_authentication=False,
        client_store=MockClientStore(),
    )
    app = create_protected_mcp_app(config)
    client = TestClient(app)
    response = client.post(
        "/register",
        json={"redirect_uris": ["https://example.com/callback"]},
    )
    assert response.status_code == HTTPStatus.CREATED
    data = response.json()
    assert "client_id" in data


def test_no_as_metadata_returns_404() -> None:
    client = _create_app(require_authentication=False)
    response = client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_no_client_store_returns_404() -> None:
    client = _create_app(require_authentication=False)
    response = client.post(
        "/register",
        json={"redirect_uris": ["https://example.com/callback"]},
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_full_discovery_flow() -> None:
    server = MCPServer(name="test-flow", version="1.0.0", tools=_TOOLS)
    config = ProtectedMCPAppConfig(
        mcp_server=server,
        token_validator=MockTokenValidator(),
        resource_uri="https://mcp.example.com",
        authorization_servers=("https://auth.example.com",),
        require_authentication=False,
        authorization_server_metadata=_AS_METADATA,
        client_store=MockClientStore(),
    )
    app = create_protected_mcp_app(config)
    client = TestClient(app)

    as_response = client.get("/.well-known/oauth-authorization-server")
    assert as_response.status_code == HTTPStatus.OK
    as_data = as_response.json()
    assert "registration_endpoint" in as_data

    reg_response = client.post(
        "/register",
        json={"redirect_uris": ["https://example.com/callback"]},
    )
    assert reg_response.status_code == HTTPStatus.CREATED
    assert "client_id" in reg_response.json()
