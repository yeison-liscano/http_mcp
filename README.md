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
- **Stateful Context**: Maintain state across tool and prompt calls using a
  context object.
- **Request Access**: Access the incoming request object from your tools and
  prompts.

## Server Types

This library provides two server classes to accommodate different use cases:

### MCPServer (Context-Aware Server)

The `MCPServer` is a generic server that supports context management and
stateful operations.

**Key Characteristics:**

- **Generic Type Parameter**: Uses `TToolsContext` as a generic type parameter
- **Context Required**: Requires a `context` parameter in the constructor
- **Full Context Support**: Tools and prompts can access and modify the shared
  context object
- **Stateful**: Maintains state across tool and prompt calls through the context
- **Flexible**: Can be used with any custom context class

**Example Usage:**

```python
from dataclasses import dataclass, field
from http_mcp.server import MCPServer

@dataclass
class Context:
    call_count: int = 0
    user_preferences: dict = field(default_factory=dict)

context = Context()
mcp_server = MCPServer(
    name="my-server",
    version="1.0.0",
    context=context,  # Pass custom context
    tools=my_tools,
    prompts=my_prompts
)
```

### SimpleServer (Stateless Server)

The `SimpleServer` is a specialized version of `MCPServer` that provides a
simpler interface for stateless operations.

**Key Characteristics:**

- **Inherits from MCPServer**: `SimpleServer` is a specialized version of
  `MCPServer`
- **Fixed Context Type**: Uses `None` as the context type (no context)
- **No Context Required**: The `context` parameter is automatically set to
  `None`
- **Stateless**: No shared state between tool and prompt calls
- **Simplified**: Easier to use when you don't need state management

**Example Usage:**

```python
from http_mcp.server import SimpleServer

simple_server = SimpleServer(
    name="my-server",
    version="1.0.0",
    tools=my_tools,
    prompts=my_prompts
    # No context needed
)
```

### When to Use Each Server Type

**Use MCPServer when:**

- You need to maintain state across tool/prompt calls
- You want to track usage, cache data, or share information between operations
- You're building a complex application that requires context awareness
- You need to access request information in your tools/prompts

**Use SimpleServer when:**

- You don't need to maintain any state
- Your tools and prompts are stateless and independent
- You want a simpler setup without context management
- You're building a basic MCP server for simple operations

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

def greet(args: Arguments[GreetInput, None]) -> GreetOutput:
    return GreetOutput(answer=f"Hello, {args.inputs.question}!")  # access inputs via args.inputs

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
from http_mcp.server import SimpleServer
from app.tools import TOOLS

mcp_server = SimpleServer(tools=TOOLS, name="test", version="1.0.0")

app = Starlette()
app.mount(
    "/mcp",
    mcp_server.app,
)

```

## Stateful Context

This is the server context attribute; it can be seen as a global state for the
server.

You can use a context object to maintain state across tool and prompt calls. The
context object is passed to each tool and prompt call and can be used to store
and retrieve data.

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
from http_mcp.types import Arguments
from app.context import Context

class MyToolArguments(BaseModel):
    question: str = Field(description="The question to answer")

class MyToolOutput(BaseModel):
    answer: str = Field(description="The answer to the question")

async def my_tool(args: Arguments[MyToolArguments, Context]) -> MyToolOutput:
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
from http_mcp.types import Arguments

class MyToolArguments(BaseModel):
    question: str = Field(description="The question to answer")

class MyToolOutput(BaseModel):
    answer: str = Field(description="The answer to the question")


async def my_tool(args: Arguments[MyToolArguments, None]) -> MyToolOutput:
    # Access the request
    auth_header = args.request.headers.get("Authorization")
    ...

    return MyToolOutput(answer=f"Hello, {args.inputs.question}!")

# For stateless tools, use SimpleServer:
from http_mcp.server import SimpleServer

simple_server = SimpleServer(
    name="my-server",
    version="1.0.0",
    tools=(my_tool,),
)
```

## Prompts

You can add interactive templates that are invoked by user choice. Prompts now
support context and request access, similar to tools.

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


def get_advice(args: Arguments[GetAdvice, None]) -> tuple[PromptMessage, ...]:
    """Get advice on a topic."""
    template = """
    You are a helpful assistant that can give advice on {topic}.
    """
    if args.inputs.include_actionable_steps:
        template += """
        The advice should include actionable steps.
        """
    return (
        PromptMessage(role="user", content=TextContent(text=template.format(topic=args.inputs.topic))),
    )


PROMPTS = (
    Prompt(
        func=get_advice,
        arguments_type=GetAdvice,
    ),
)
```

2. **Using prompts with context:**

```python
from pydantic import BaseModel, Field
from http_mcp.mcp_types.content import TextContent
from http_mcp.mcp_types.prompts import PromptMessage
from http_mcp.types import Arguments, Prompt
from app.context import Context

class GetAdvice(BaseModel):
    topic: str = Field(description="The topic to get advice on")

def get_advice_with_context(args: Arguments[GetAdvice, Context]) -> tuple[PromptMessage, ...]:
    """Get advice on a topic with context awareness."""
    # Access the context
    called_tools = args.context.get_called_tools()
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
from http_mcp.server import SimpleServer

app = Starlette()
mcp_server = SimpleServer(tools=(), prompts=PROMPTS, name="test", version="1.0.0")

app.mount(
    "/mcp",
    mcp_server.app,
)

```
