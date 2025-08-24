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
- **Server State Management**: Access shared state through the lifespan context
  using the `get_state_key` method.
- **Request Access**: Access the incoming request object from your tools and
  prompts.

## Server Architecture

The library provides a single `MCPServer` class that uses lifespan to manage
shared state across the entire application lifecycle.

### MCPServer

The `MCPServer` is designed to work with Starlette's lifespan system for
managing shared server state.

**Key Characteristics:**

- **Lifespan Based**: Uses Starlette's lifespan events to initialize and manage
  shared server state
- **Application-Level State**: State persists across the entire application
  lifecycle, not per-request
- **Flexible**: Can be used with any custom context class stored in the lifespan
  state

**Example Usage:**

```python
import contextlib
from collections.abc import AsyncIterator
from typing import TypedDict
from dataclasses import dataclass, field
from starlette.applications import Starlette
from http_mcp.server import MCPServer

@dataclass
class Context:
    call_count: int = 0
    user_preferences: dict = field(default_factory=dict)

class State(TypedDict):
    context: Context

@contextlib.asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[State]:
    yield {"context": Context()}

mcp_server = MCPServer(
    name="my-server",
    version="1.0.0",
    tools=my_tools,
    prompts=my_prompts
)

app = Starlette(lifespan=lifespan)
app.mount("/mcp", mcp_server.app)
```

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
from http_mcp.types import Arguments

from app.tools.models import GreetInput, GreetOutput

def greet(args: Arguments[GreetInput]) -> GreetOutput:
    return GreetOutput(answer=f"Hello, {args.inputs.question}!")

```

```python
# app/tools/__init__.py

from http_mcp.types import Tool
from app.tools.models import GreetInput, GreetOutput
from app.tools.tools import greet

TOOLS = (
    Tool(
        func=greet,
        inputs=GreetInput,
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

## Server State Management

The server uses Starlette's lifespan system to manage shared state across the
entire application lifecycle. State is initialized when the application starts
and persists until it shuts down. Context is accessed through the
`get_state_key` method on the `Arguments` object.

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

2. **Set up the application with lifespan:**

```python
import contextlib
from collections.abc import AsyncIterator
from typing import TypedDict
from starlette.applications import Starlette
from app.context import Context
from http_mcp.server import MCPServer

class State(TypedDict):
    context: Context

@contextlib.asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[State]:
    yield {"context": Context(called_tools=[])}

mcp_server = MCPServer(
    tools=TOOLS,
    name="test",
    version="1.0.0",
)

app = Starlette(lifespan=lifespan)
app.mount("/mcp", mcp_server.app)
```

3. **Access the context in your tools:**

```python
from pydantic import BaseModel, Field
from http_mcp.types import Arguments
from app.context import Context

class MyToolArguments(BaseModel):
    question: str = Field(description="The question to answer")

class MyToolOutput(BaseModel):
    answer: str = Field(description="The answer to the question")

async def my_tool(args: Arguments[MyToolArguments]) -> MyToolOutput:
    # Access the context from lifespan state
    context = args.get_state_key("context", Context)
    context.add_called_tool("my_tool")
    ...

    return MyToolOutput(answer=f"Hello, {args.inputs.question}!")
```

## Request Access

You can access the incoming request object from your tools. The request object
is passed to each tool call and can be used to access headers, cookies, and
other request data (e.g. request.state, request.scope).

```python
from pydantic import BaseModel, Field
from http_mcp.types import Arguments

class MyToolArguments(BaseModel):
    question: str = Field(description="The question to answer")

class MyToolOutput(BaseModel):
    answer: str = Field(description="The answer to the question")


async def my_tool(args: Arguments[MyToolArguments]) -> MyToolOutput:
    # Access the request
    auth_header = args.request.headers.get("Authorization")
    ...

    return MyToolOutput(answer=f"Hello, {args.inputs.question}!")

# Use MCPServer:
from http_mcp.server import MCPServer

mcp_server = MCPServer(
    name="my-server",
    version="1.0.0",
    tools=(my_tool,),
)
```

## Prompts

You can add interactive templates that are invoked by user choice. Prompts now
support lifespan state access, similar to tools.

1. **Define the arguments for the prompts:**

```python
from pydantic import BaseModel, Field

from http_mcp.mcp_types.content import TextContent
from http_mcp.mcp_types.prompts import PromptMessage
from http_mcp.types import Arguments, Prompt


class GetAdvice(BaseModel):
    topic: str = Field(description="The topic to get advice on")
    include_actionable_steps: bool = Field(
        description="Whether to include actionable steps in the advice", default=False
    )


def get_advice(args: Arguments[GetAdvice]) -> tuple[PromptMessage, ...]:
    """Get advice on a topic."""
    template = """
    You are a helpful assistant that can give advice on {topic}.
    """
    if args.inputs.include_actionable_steps:
        template += """
        The advice should include actionable steps.
        """
    return (
        PromptMessage(
            role="user",
            content=TextContent(
                text=template.format(topic=args.inputs.topic)
            ),
        ),
    )


PROMPTS = (
    Prompt(
        func=get_advice,
        arguments_type=GetAdvice,
    ),
)
```

2. **Using prompts with lifespan state:**

```python
from pydantic import BaseModel, Field
from http_mcp.mcp_types.content import TextContent
from http_mcp.mcp_types.prompts import PromptMessage
from http_mcp.types import Arguments, Prompt
from app.context import Context

class GetAdvice(BaseModel):
    topic: str = Field(description="The topic to get advice on")

def get_advice_with_context(args: Arguments[GetAdvice]) -> tuple[PromptMessage, ...]:
    """Get advice on a topic with context awareness."""
    # Access the context from lifespan state
    context = args.get_state_key("context", Context)
    called_tools = context.get_called_tools()
    template = """
    You are a helpful assistant that can give advice on {topic}.
    Previously called tools: {tools}
    """

    return (
        PromptMessage(
            role="user",
            content=TextContent(
                text=template.format(
                    topic=args.inputs.topic,
                    tools=", ".join(called_tools) if called_tools else "none"
                )
            )
        ),
    )

PROMPTS_WITH_CONTEXT = (
    Prompt(
        func=get_advice_with_context,
        arguments_type=GetAdvice,
    ),
)
```

3. **Instantiate the server:**

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
