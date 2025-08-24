import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from typing import TypedDict

import uvicorn
from starlette.applications import Starlette

from http_mcp.server import MCPServer
from tests.app.context import Context
from tests.app.prompts import PROMPTS
from tests.app.tools import TOOLS

mcp_server = MCPServer(tools=TOOLS, prompts=PROMPTS, name="test", version="1.0.0")


class State(TypedDict):
    context: Context


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[State]:
    yield {"context": Context(called_tools=[])}


def mount_mcp_server(mcp_server: MCPServer) -> Starlette:
    app = Starlette(lifespan=lifespan)
    app.mount("/mcp", mcp_server.app)
    return app


def run_http() -> None:
    app = Starlette(
        lifespan=lifespan,
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
