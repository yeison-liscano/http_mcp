# Simple HTTP MCP Server Implementation

This project provides a lightweight server implementation for the Model Context
Protocol (MCP) over HTTP. It allows you to expose Python functions as tools and
prompts that can be discovered and executed remotely via a JSON-RPC interface.
It is intended to be used with a Starlette or FastAPI application (see
[demo](https://github.com/yeison-liscano/demo_http_mcp)).

The following badge corresponds to the example server for this project. Find it
in the [tests/app/ folder](tests/app).

<a href="https://glama.ai/mcp/servers/@yeison-liscano/http_mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@yeison-liscano/http_mcp/badge" alt="Simple HTTP Server MCP server" />
</a>

## Features

- **MCP Protocol Compliant**: Implements the MCP specification for tool and
  prompts discovery and execution. No support for notifications.
- **HTTP and STDIO Transport**: Uses HTTP (POST requests) or STDIO for
  communication.
- **Async Support**: Built on `Starlette` or `FastAPI` for asynchronous request
  handling.
- **Type-Safe**: Leverages `Pydantic` for robust data validation and
  serialization.
- **Stateful Context**: Maintain state across tool calls using a context object.
- **Request Access**: Access the incoming request object from your tools.

## Tools

Tools are the functions that can be called by the client.

Example:

1. **Define the arguments and output for the tools:**

```python
# app/tools/models.py
from pydantic import BaseModel, Field

class GreetInput(BaseModel):
    question: str = Field(description="The question to answer")

class GreetOutput(BaseModel):
    answer: str = Field(description="The answer to the question")

# Note: the description on Field will be passed when listing the tools.
# Having a description is optional, but it's recommended to provide one.
```

2. **Define the tools:**

```python
# app/tools/tools.py
from http_mcp.tools import ToolArguments

from app.tools.models import GreetInput, GreetOutput

def greet(args: ToolArguments[GreetInput, None]) -> GreetOutput:
    return GreetOutput(answer=f"Hello, {args.inputs.question}!")  # access inputs via args.inputs

```

```python
# app/tools/__init__.py

from http_mcp.tools import Tool
from app.tools.models import GreetInput, GreetOutput
from app.tools.tools import greet

TOOLS = (
    Tool(
        func=greet,
        input=GreetInput,
        output=GreetOutput,
    ),
)

__all__ = ["TOOLS"]

```

3. **Instantiate the server:**

```python
# app/main.py
from starlette.applications import Starlette
from http_mcp.server import MCPServer
from app.tools import TOOLS

mcp_server = MCPServer(tools=TOOLS, name="test", version="1.0.0")

app = Starlette()
app.mount(
    "/mcp",
    mcp_server.app,
)

```

## Stateful Context

This is the server context attribute; it can be seen as a global state for the
server.

You can use a context object to maintain state across tool calls. The context
object is passed to each tool call and can be used to store and retrieve data.

Example:

1. **Define a context class:**

```python
from dataclasses import dataclass, field

# app/context.py

@dataclass
class Context:
    called_tools: list[str] = field(default_factory=list)

    def get_called_tools(self) -> list[str]:
        return self.called_tools

    def add_called_tool(self, tool_name: str) -> None:
        self.called_tools.append(tool_name)
```

1. **Instantiate the context and the server:**

```python
from app.tools import TOOLS
from app.context import Context
from http_mcp.server import MCPServer

mcp_server: MCPServer[Context] = MCPServer(
    tools=TOOLS,
    name="test",
    version="1.0.0",
    context=Context(called_tools=[]),
)
```

1. **Access the context in your tools:**

```python
from pydantic import BaseModel, Field
from http_mcp.tools import ToolArguments
from app.context import Context

class MyToolArguments(BaseModel):
    question: str = Field(description="The question to answer")

class MyToolOutput(BaseModel):
    answer: str = Field(description="The answer to the question")

async def my_tool(args: ToolArguments[MyToolArguments, Context]) -> MyToolOutput:
    # Access the context
    args.context.add_called_tool("my_tool")
    ...

    return MyToolOutput(answer=f"Hello, {args.inputs.question}!")
```

## Stateless Context

You can access the incoming request object from your tools. The request object
is passed to each tool call and can be used to access headers, cookies, and
other request data (e.g. request.state, request.scope).

```python
from pydantic import BaseModel, Field
from http_mcp.tools import ToolArguments

class MyToolArguments(BaseModel):
    question: str = Field(description="The question to answer")

class MyToolOutput(BaseModel):
    answer: str = Field(description="The answer to the question")


async def my_tool(args: ToolArguments[MyToolArguments, None]) -> MyToolOutput:
    # Access the request
    auth_header = args.request.headers.get("Authorization")
    ...

    return MyToolOutput(answer=f"Hello, {args.inputs.question}!")
```

## Prompts

You can add interactive templates that are invoked by user choice.

1. **Define the arguments and output for the prompts:**

```python
from pydantic import BaseModel, Field

from http_mcp.mcp_types.content import TextContent
from http_mcp.mcp_types.prompts import PromptMessage
from http_mcp.prompts import Prompt


class GetAdvice(BaseModel):
    topic: str = Field(description="The topic to get advice on")
    include_actionable_steps: bool = Field(
        description="Whether to include actionable steps in the advice", default=False
    )


def get_advice(args: GetAdvice) -> tuple[PromptMessage, ...]:
    """Get advice on a topic."""
    template = """
    You are a helpful assistant that can give advice on {topic}.
    """
    if args.include_actionable_steps:
        template += """
        The advice should include actionable steps.
        """
    return (
        PromptMessage(role="user", content=TextContent(text=template.format(topic=args.topic))),
    )


PROMPTS = (
    Prompt(
        func=get_advice,
        arguments_type=GetAdvice,
    ),
)
```

2. **Instantiate the server:**

```python
from starlette.applications import Starlette

from app.prompts import PROMPTS
from http_mcp.server import MCPServer

app = Starlette()
mcp_server = MCPServer(tools=(), prompts=PROMPTS, name="test", version="1.0.0")

app.mount(
    "/mcp",
    mcp_server.app,
)

```
