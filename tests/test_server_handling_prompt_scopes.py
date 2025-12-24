from http import HTTPStatus

from starlette.testclient import TestClient

from http_mcp._json_rcp_types.errors import ErrorCode
from http_mcp._mcp_types.content import TextContent
from http_mcp._mcp_types.prompts import PromptMessage
from http_mcp.server import MCPServer
from http_mcp.types import Prompt
from tests.app.main import BasicAuthBackend, mount_mcp_server

HEADER_AUTHORIZATION = {"Authorization": "Bearer TEST_TOKEN"}


def test_call_prompt_with_scope() -> None:
    def prompt_with_scope() -> tuple[PromptMessage, ...]:
        """Private prompt.

        Only accessible to authenticated users with the 'private' scope.
        """
        return (
            PromptMessage(
                role="user",
                content=TextContent(text="This is a private prompt."),
            ),
        )

    server = MCPServer(
        tools=(),
        name="test",
        version="1.0.0",
        prompts=(
            Prompt(
                func=prompt_with_scope,
                arguments_type=type(None),
                scopes=("private",),
            ),
        ),
    )
    app = mount_mcp_server(server, BasicAuthBackend(("private",)))
    with TestClient(app, headers={"Authorization": "Bearer TEST_TOKEN"}) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "prompts/get",
                "id": 1,
                "params": {
                    "name": "prompt_with_scope",
                    "arguments": {},
                },
            },
        )
        assert response.status_code == HTTPStatus.OK
        response_json = response.json()
        assert response_json == {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "description": (
                    "Private prompt.\n"
                    "\n"
                    "Only accessible to authenticated users with the 'private' scope.\n"
                ),
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "text": "This is a private prompt.",
                            "type": "text",
                        },
                    },
                ],
            },
        }


def test_call_prompt_without_required_scope() -> None:
    def prompt_with_scope() -> tuple[PromptMessage, ...]:
        """Private prompt.

        Only accessible to authenticated users with the 'private' scope.
        """
        return (
            PromptMessage(
                role="user",
                content=TextContent(text="This is a private prompt."),
            ),
        )

    server = MCPServer(
        tools=(),
        name="test",
        version="1.0.0",
        prompts=(
            Prompt(
                func=prompt_with_scope,
                arguments_type=type(None),
                scopes=("private",),
            ),
        ),
    )
    app = mount_mcp_server(server, BasicAuthBackend(("non_sufficient_scope",)))
    with TestClient(app, headers={"Authorization": "Bearer TEST_TOKEN"}) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "prompts/get",
                "id": 1,
                "params": {
                    "name": "prompt_with_scope",
                    "arguments": {},
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
                "message": "Prompt prompt_with_scope not found",
            },
        }
