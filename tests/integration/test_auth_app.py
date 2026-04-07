"""Integration tests for auth_mcp with the test app's tools and prompts.

Uses create_protected_mcp_app() with the same TOOLS and PROMPTS from
tests/app/ to verify the full OAuth 2.1 authorization flow end-to-end.
"""

from http import HTTPStatus

from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.testclient import TestClient

from auth_mcp.resource_server.integration import ProtectedMCPAppConfig, create_protected_mcp_app
from auth_mcp.resource_server.token_validator import TokenInfo, TokenValidator
from auth_mcp.types.metadata import ProtectedResourceMetadata
from http_mcp.server import MCPServer
from tests.fixtures.main import lifespan
from tests.fixtures.prompts import PROMPTS
from tests.fixtures.tools import TOOLS

_VALID_TOKEN = "test_oauth_token"  # noqa: S105
_RESOURCE_URI = AnyHttpUrl("https://mcp.example.com")
_AUTH_SERVER = AnyHttpUrl("https://auth.example.com")


class _MockTokenValidator(TokenValidator):
    """Token validator that grants configurable scopes for a known token."""

    def __init__(self, scopes: tuple[str, ...] = ()) -> None:
        self._scopes = scopes

    async def validate_token(
        self,
        token: str,
        resource: str | None = None,
    ) -> TokenInfo | None:
        if token == _VALID_TOKEN:
            return TokenInfo(
                subject="testuser@example.com",
                scopes=self._scopes,
                client_id="test_client",
                audience=resource,
            )
        return None


def _create_starlette_app(
    *,
    scopes: tuple[str, ...] = (),
    require_authentication: bool = True,
) -> Starlette:
    """Return raw Starlette app (use with ``with TestClient(app) as client:``)."""
    server = MCPServer(name="test", version="1.0.0", tools=TOOLS, prompts=PROMPTS)
    config = ProtectedMCPAppConfig(
        mcp_server=server,
        token_validator=_MockTokenValidator(scopes=scopes),
        resource_endpoint=ProtectedResourceMetadata(
            resource=_RESOURCE_URI,
            authorization_servers=(_AUTH_SERVER,),
            scopes_supported=("private", "superuser"),
        ),
        require_authentication=require_authentication,
    )
    return create_protected_mcp_app(config, lifespan=lifespan)


def _create_app(
    *,
    scopes: tuple[str, ...] = (),
    require_authentication: bool = True,
) -> TestClient:
    return TestClient(
        _create_starlette_app(scopes=scopes, require_authentication=require_authentication),
    )


def _post_mcp(
    client: TestClient,
    method: str,
    params: dict | None = None,
    *,
    authenticated: bool = True,
) -> dict:
    headers = {"Authorization": f"Bearer {_VALID_TOKEN}"} if authenticated else {}
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": method, "id": 1, "params": params or {}},
        headers=headers,
    )
    return {"status": response.status_code, "headers": response.headers, "json": response.json()}


# --- Discovery endpoint ---


def test_metadata_endpoint_returns_resource_info() -> None:
    client = _create_app()
    response = client.get("/.well-known/oauth-protected-resource/mcp/")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["resource"] == str(_RESOURCE_URI)
    assert str(_AUTH_SERVER) in data["authorization_servers"]
    assert data["scopes_supported"] == ["private", "superuser"]


def test_metadata_endpoint_has_security_headers() -> None:
    client = _create_app(require_authentication=False)
    response = client.get("/.well-known/oauth-protected-resource/mcp/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "max-age=" in response.headers["strict-transport-security"]


# --- Unauthenticated requests ---


def test_unauthenticated_request_returns_401() -> None:
    client = _create_app()
    result = _post_mcp(client, "tools/list", authenticated=False)
    assert result["status"] == HTTPStatus.UNAUTHORIZED
    assert "www-authenticate" in result["headers"]
    www_auth = result["headers"]["www-authenticate"]
    assert "Bearer" in www_auth
    assert "resource_metadata=" in www_auth


def test_unauthenticated_401_has_security_headers() -> None:
    client = _create_app()
    result = _post_mcp(client, "tools/list", authenticated=False)
    assert result["headers"]["x-content-type-options"] == "nosniff"
    assert result["headers"]["cache-control"] == "no-store"
    assert "max-age=" in result["headers"]["strict-transport-security"]


def test_unauthenticated_401_body_is_oauth_error() -> None:
    client = _create_app()
    result = _post_mcp(client, "tools/list", authenticated=False)
    body = result["json"]
    assert body["error"] == "invalid_token"
    assert "error_description" in body


def test_invalid_token_returns_401() -> None:
    client = _create_app()
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}},
        headers={"Authorization": "Bearer wrong_token"},
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED


# --- Unauthenticated with require_authentication=False ---


def test_unauthenticated_sees_public_tools_when_not_required() -> None:
    client = _create_app(require_authentication=False)
    result = _post_mcp(client, "tools/list", authenticated=False)
    assert result["status"] == HTTPStatus.OK
    tool_names = [t["name"] for t in result["json"]["result"]["tools"]]
    for tool in TOOLS:
        if not tool.scopes:
            assert tool.name in tool_names
        else:
            assert tool.name not in tool_names


def test_unauthenticated_sees_public_prompts_when_not_required() -> None:
    client = _create_app(require_authentication=False)
    result = _post_mcp(client, "prompts/list", authenticated=False)
    assert result["status"] == HTTPStatus.OK
    prompt_names = [p["name"] for p in result["json"]["result"]["prompts"]]
    for prompt in PROMPTS:
        if not prompt.scopes:
            assert prompt.name in prompt_names
        else:
            assert prompt.name not in prompt_names


# --- Authenticated with no scopes ---


def test_authenticated_no_scopes_sees_only_public_tools() -> None:
    client = _create_app(scopes=())
    result = _post_mcp(client, "tools/list")
    assert result["status"] == HTTPStatus.OK
    tool_names = [t["name"] for t in result["json"]["result"]["tools"]]
    for tool in TOOLS:
        if not tool.scopes:
            assert tool.name in tool_names
        else:
            assert tool.name not in tool_names


def test_authenticated_no_scopes_sees_only_public_prompts() -> None:
    client = _create_app(scopes=())
    result = _post_mcp(client, "prompts/list")
    assert result["status"] == HTTPStatus.OK
    prompt_names = [p["name"] for p in result["json"]["result"]["prompts"]]
    for prompt in PROMPTS:
        if not prompt.scopes:
            assert prompt.name in prompt_names
        else:
            assert prompt.name not in prompt_names


# --- Authenticated with "private" scope ---
# Note: Starlette's has_required_scope requires ALL listed scopes.
# So ("private",) grants access to tools with scopes=("private",)
# but NOT tools with scopes=("private", "superuser").


def test_private_scope_sees_single_scope_tools() -> None:
    client = _create_app(scopes=("private",))
    result = _post_mcp(client, "tools/list")
    assert result["status"] == HTTPStatus.OK
    tool_names = [t["name"] for t in result["json"]["result"]["tools"]]
    assert "private_tool" in tool_names
    assert "get_weather" in tool_names
    # multi-scope tool requires BOTH "private" AND "superuser"
    assert "private_multi_scope_tool" not in tool_names


def test_private_scope_sees_single_scope_prompts() -> None:
    client = _create_app(scopes=("private",))
    result = _post_mcp(client, "prompts/list")
    assert result["status"] == HTTPStatus.OK
    prompt_names = [p["name"] for p in result["json"]["result"]["prompts"]]
    assert "private_prompt" in prompt_names
    assert "get_advice" in prompt_names
    assert "private_multi_scope_prompt" not in prompt_names


# --- Authenticated with both scopes ---


def test_all_scopes_sees_all_tools() -> None:
    client = _create_app(scopes=("private", "superuser"))
    result = _post_mcp(client, "tools/list")
    assert result["status"] == HTTPStatus.OK
    tool_names = [t["name"] for t in result["json"]["result"]["tools"]]
    for tool in TOOLS:
        assert tool.name in tool_names


def test_all_scopes_sees_all_prompts() -> None:
    client = _create_app(scopes=("private", "superuser"))
    result = _post_mcp(client, "prompts/list")
    assert result["status"] == HTTPStatus.OK
    prompt_names = [p["name"] for p in result["json"]["result"]["prompts"]]
    for prompt in PROMPTS:
        assert prompt.name in prompt_names


# --- Tool invocation ---


def test_call_public_tool_with_valid_token() -> None:
    app = _create_starlette_app(scopes=("private",))
    with TestClient(app, headers={"Authorization": f"Bearer {_VALID_TOKEN}"}) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {"name": "get_weather", "arguments": {"location": "London"}},
            },
        )
        assert response.status_code == HTTPStatus.OK
        result = response.json()
        assert result["result"]["isError"] is False
        assert "London" in result["result"]["structuredContent"]["weather"]


def test_call_private_tool_with_matching_scope() -> None:
    app = _create_starlette_app(scopes=("private",))
    with TestClient(app, headers={"Authorization": f"Bearer {_VALID_TOKEN}"}) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {"name": "private_tool", "arguments": {}},
            },
        )
        assert response.status_code == HTTPStatus.OK
        result = response.json()
        assert result["result"]["isError"] is False
        assert result["result"]["structuredContent"]["success"] is True


def test_call_private_tool_without_scope_returns_error() -> None:
    app = _create_starlette_app(scopes=())
    with TestClient(app, headers={"Authorization": f"Bearer {_VALID_TOKEN}"}) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {"name": "private_tool", "arguments": {}},
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.json() == {"error": "insufficient_scope"}


def test_call_tool_unauthenticated_returns_401() -> None:
    client = _create_app()
    result = _post_mcp(
        client,
        "tools/call",
        {"name": "get_weather", "arguments": {"location": "London"}},
        authenticated=False,
    )
    assert result["status"] == HTTPStatus.UNAUTHORIZED


# --- Prompt invocation ---


def test_get_public_prompt_with_valid_token() -> None:
    client = _create_app(scopes=())
    result = _post_mcp(
        client,
        "prompts/get",
        {"name": "get_advice", "arguments": {"topic": "security"}},
    )
    assert result["status"] == HTTPStatus.OK
    messages = result["json"]["result"]["messages"]
    assert len(messages) > 0
    assert "security" in messages[0]["content"]["text"]


def test_get_private_prompt_without_scope_returns_error() -> None:
    client = _create_app(scopes=())
    result = _post_mcp(
        client,
        "prompts/get",
        {"name": "private_prompt", "arguments": {}},
    )
    assert result["status"] == HTTPStatus.FORBIDDEN
    assert result["json"] == {"error": "insufficient_scope"}


def test_get_prompt_unauthenticated_returns_401() -> None:
    client = _create_app()
    result = _post_mcp(
        client,
        "prompts/get",
        {"name": "get_advice", "arguments": {"topic": "test"}},
        authenticated=False,
    )
    assert result["status"] == HTTPStatus.UNAUTHORIZED


# --- Initialize ---


def test_initialize_with_valid_token() -> None:
    client = _create_app(scopes=())
    result = _post_mcp(
        client,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0.0"},
        },
    )
    assert result["status"] == HTTPStatus.OK
    assert result["json"]["result"]["serverInfo"]["name"] == "test"
    assert result["json"]["result"]["serverInfo"]["version"] == "1.0.0"


def test_initialize_unauthenticated_returns_401() -> None:
    client = _create_app()
    result = _post_mcp(
        client,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0.0"},
        },
        authenticated=False,
    )
    assert result["status"] == HTTPStatus.UNAUTHORIZED


# --- Insufficient scope: 403 + WWW-Authenticate ---


def test_insufficient_scope_tool_returns_403() -> None:
    client = _create_app(scopes=())
    result = _post_mcp(
        client,
        "tools/call",
        {"name": "private_tool", "arguments": {}},
    )
    assert result["status"] == HTTPStatus.FORBIDDEN


def test_insufficient_scope_tool_has_www_authenticate_header() -> None:
    client = _create_app(scopes=())
    result = _post_mcp(
        client,
        "tools/call",
        {"name": "private_tool", "arguments": {}},
    )
    assert "www-authenticate" in result["headers"]
    www_auth = result["headers"]["www-authenticate"]
    assert "Bearer" in www_auth
    assert "insufficient_scope" in www_auth
    assert "resource_metadata=" in www_auth


def test_insufficient_scope_tool_has_security_headers() -> None:
    client = _create_app(scopes=())
    result = _post_mcp(
        client,
        "tools/call",
        {"name": "private_tool", "arguments": {}},
    )
    assert result["headers"]["x-content-type-options"] == "nosniff"
    assert result["headers"]["cache-control"] == "no-store"
    assert "max-age=" in result["headers"]["strict-transport-security"]


def test_insufficient_scope_prompt_returns_403() -> None:
    client = _create_app(scopes=())
    result = _post_mcp(
        client,
        "prompts/get",
        {"name": "private_prompt", "arguments": {}},
    )
    assert result["status"] == HTTPStatus.FORBIDDEN


def test_insufficient_scope_prompt_has_www_authenticate_header() -> None:
    client = _create_app(scopes=())
    result = _post_mcp(
        client,
        "prompts/get",
        {"name": "private_prompt", "arguments": {}},
    )
    assert "www-authenticate" in result["headers"]
    www_auth = result["headers"]["www-authenticate"]
    assert "Bearer" in www_auth
    assert "insufficient_scope" in www_auth
