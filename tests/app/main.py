import asyncio
import contextlib
import os
from collections.abc import AsyncIterator, Sequence
from typing import TypedDict

import uvicorn
from starlette.applications import Starlette
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    BaseUser,
    SimpleUser,
    UnauthenticatedUser,
)
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import HTTPConnection

from http_mcp.server import MCPServer
from tests.app.context import Context
from tests.app.prompts import PROMPTS
from tests.app.tools import TOOLS

mcp_server = MCPServer(tools=TOOLS, prompts=PROMPTS, name="test", version="1.0.0")


class BasicAuthBackend(AuthenticationBackend):
    """Basic authentication backend that mocks the authentication.

    It allows access to the server with the granted scopes if the authorization header is set to
    "Bearer TEST_TOKEN" and returns an unauthenticated user otherwise.
    """

    def __init__(self, granted_scopes: Sequence[str] = ("authenticated",)) -> None:
        self.granted_scopes = granted_scopes
        super().__init__()

    async def authenticate(self, conn: HTTPConnection) -> tuple[AuthCredentials, BaseUser]:
        if conn.headers.get("Authorization") == "Bearer TEST_TOKEN":
            return AuthCredentials(self.granted_scopes), SimpleUser("unittesting@mcp.com")
        return AuthCredentials(), UnauthenticatedUser()


class State(TypedDict):
    context: Context


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[State]:
    yield {"context": Context(called_tools=[])}


def mount_mcp_server(
    server: MCPServer,
    authentication_backend: AuthenticationBackend | None = None,
) -> Starlette:
    app = Starlette(
        lifespan=lifespan,
        middleware=[
            Middleware(
                AuthenticationMiddleware,
                backend=authentication_backend,
            ),
        ]
        if authentication_backend
        else None,
    )
    app.mount("/mcp", server.app)
    return app


def run_http() -> None:
    app = Starlette(
        lifespan=lifespan,
        middleware=[
            Middleware(
                AuthenticationMiddleware,
                backend=BasicAuthBackend(granted_scopes=("private",)),
            ),
        ],
    )
    app.mount(
        "/mcp",
        mcp_server.app,
    )
    uvicorn.run(app, host="localhost", port=8000)


def run_stdio() -> None:
    request_headers = {
        "Authorization": os.getenv("AUTHORIZATION_TOKEN", ""),
    }
    asyncio.run(mcp_server.serve_stdio(request_headers), debug=True)


if __name__ == "__main__":
    run_http()
