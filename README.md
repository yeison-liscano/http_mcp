# Simple HTTP MCP Server Implementation

This project provides a lightweight server implementation for the Model Context Protocol (MCP) over HTTP. It allows you to expose Python functions as "tools" that can be discovered and executed remotely via a JSON-RPC interface. It is thought to be used with an Starlette or FastAPI application (see [app/main.py](app/main.py)).


## Features

- **MCP Protocol Compliant**: Implements the MCP specification for tool and prompts discovery and execution.
- **HTTP and STDIO Transport**: Uses HTTP (POST requests) or STDIO for communication.
- **Async Support**: Built on `Starlette` or `FastAPI` for asynchronous request handling.
- **Type-Safe**: Leverages `Pydantic` for robust data validation and serialization.
- **Stateful Context**: Maintain state across tool calls using a context object.
- **Request Access**: Access the incoming request object from your tools.
- **Dependency Management**: Uses `uv` for fast and efficient package management.
- **Linting**: Integrated with `Ruff` for code formatting and linting.
- **Type Checking**: Uses `Mypy` for static type checking.


## Tools

Tools are the functions that can be called by the client.

Example:

```python
# app/tools/models.py
from pydantic import BaseModel, Field
from server.tools import Tool, ToolArguments

class Tool1Arguments(BaseModel):
    question: str = Field(description="The question to answer")

class Tool1Output(BaseModel):
    answer: str = Field(description="The answer to the question")

class Tool2Arguments(BaseModel):
    question: str = Field(description="The question to answer")

class Tool2Output(BaseModel):
    answer: str = Field(description="The answer to the question")

# Note: the description on Field will be passed when listing the tools.
# Having a description is optional, but it's recommended to provide one.

# --------- ------------ --------- --------- ------------ --------- ------------ ---------
# app/tools/tools.py
import asyncio

def tool_1(args: ToolArguments[Tool1Arguments, None]) -> Tool1Output:
    return Tool1Output(answer=f"Hello, {args.inputs.question}!")

async def tool_2(args: ToolArguments[Tool2Arguments, None]) -> Tool2Output:
    await asyncio.sleep(1)
    return Tool2Output(answer=f"Hello, {args.inputs.question}!")

# --------- ------------ --------- --------- ------------ --------- ------------ ---------
# app/tools/__init__.py

from app.tools.models import Tool1Arguments, Tool1Output, Tool2Arguments, Tool2Output
from app.tools.tools import tool_1, tool_2
from server.tools import Tool

TOOLS = (
    Tool(
        func=tool_1,
        input=Tool1Arguments,
        output=Tool1Output,
    ),
    Tool(
        func=tool_2,
        input=Tool2Arguments,
        output=Tool2Output,
    ),
)

__all__ = ["TOOLS"]

# --------- ------------ --------- --------- ------------ --------- ------------ ---------
# app/main.py
from starlette.applications import Starlette
from server.server import MCPServer
from app.tools import TOOLS

# MCPServer[ContextType]
mcp_server: MCPServer[None] = MCPServer(tools=TOOLS, name="test", version="1.0.0")

app = Starlette()
app.mount(
    "/mcp",
    mcp_server.app,
)

```


## Stateful Context

This is the server context attribute, it could be seem as a global state for the server.

You can use a context object to maintain state across tool calls. The context object is passed to each tool call and can be used to store and retrieve data.

Example:

1.  **Define a context class:**
    ```python
    from dataclasses import dataclass, field

    @dataclass
    class Context:
        called_tools: list[str] = field(default_factory=list)

        def get_called_tools(self) -> list[str]:
            return self.called_tools

        def add_called_tool(self, tool_name: str) -> None:
            self.called_tools.append(tool_name)
    ```

2.  **Instantiate the context and the server:**
    ```python
    from app.tools import TOOLS, Context
    from server.server import MCPServer

    mcp_server: MCPServer[Context] = MCPServer(tools=TOOLS, name="test", version="1.0.0", context=Context(called_tools=[]))
    ```

3.  **Access the context in your tools:**
    ```python
    from server.tools import ToolArguments
    from app.tools import Context

    async def my_tool(args: ToolArguments[MyToolArguments, Context]) -> MyToolOutput:
        # Access the context
        args.context.add_called_tool("my_tool")
        ...
    ```

## Stateless Context

You can access the incoming request object from your tools. The request object is passed to each tool call and can be used to access headers, cookies, and other request data (e.x request.state, request.scope).

```python
from server.tools import ToolArguments

async def my_tool(args: ToolArguments[MyToolArguments, None]) -> MyToolOutput:
    # Access the request
    auth_header = args.request.headers.get("Authorization")
    ...
```

## Getting Started

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd simple-http-mcp
    ```

2.  **Create a virtual environment and install dependencies:**
    ```bash
    uv venv
    source .venv/bin/activate
    uv sync
    ```

## Usage

For usage examples, please refer to the tests in the `tests/` directory.

## How to test with Gemini Cli

1.  **Install dependencies:**
    ```bash
    uv sync
    ```

2.  **Run the server:**
    ```bash
    uv run run-http
    ```
    or for stdio transport:
    ```bash
    uv run run-stdio
    ```

3.  **Test the server:**

    Note: you should be located on the root folder of the project so gemini config is used.

    ```bash
    gemini
    /mcp # This should show the tools available
    ```

Example:

![Example](assets/gemini_test.png)


## Development

This project uses several tools to ensure code quality.

### Linting

To check for linting errors, run:

```bash
ruff check .
```

To automatically fix linting errors, run:

```bash
ruff check . --fix
```

### Type Checking

To run the static type checker, use:

```bash
mypy .
```