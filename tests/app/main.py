import asyncio
import os

import uvicorn
from starlette.applications import Starlette

from http_mcp.server import MCPServer
from tests.app.prompts import PROMPTS
from tests.app.tools import TOOLS, Context

app = Starlette()
context = Context(called_tools=[])
mcp_server = MCPServer(tools=TOOLS, prompts=PROMPTS, name="test", version="1.0.0", context=context)

app.mount(
    "/mcp",
    mcp_server.app,
)


def run_http() -> None:
    uvicorn.run(app, host="localhost", port=8000)


def run_stdio() -> None:
    request_headers = {
        "Authorization": os.getenv("AUTHORIZATION_TOKEN", ""),
    }
    asyncio.run(mcp_server.serve_stdio(request_headers), debug=True)
