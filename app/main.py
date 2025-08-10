import uvicorn
from starlette.applications import Starlette

from app.tools import TOOLS
from server.server import MCPServer

app = Starlette()
mcp_server = MCPServer(tools=TOOLS, name="test", version="1.0.0", endpoint="/mcp", context=None)

app.mount(
    "/mcp",
    mcp_server.app,
)


def main() -> None:
    uvicorn.run(app, host="localhost", port=8000)


if __name__ == "__main__":
    main()
