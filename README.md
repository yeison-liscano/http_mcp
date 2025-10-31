# Simple HTTP MCP Server Implementation

This project provides a lightweight server implementation for the Model Context
Protocol (MCP) over HTTP. It allows you to expose Python functions as tools and
prompts that can be discovered and executed remotely via a JSON-RPC interface.
It is intended to be used with a Starlette or FastAPI application (see
[demo](https://github.com/yeison-liscano/demo_http_mcp)).

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Server Architecture](#server-architecture)
- [Tools](#tools)
  - [Basic Tool Example](#basic-tool-example)
  - [Tools Without Arguments](#tools-without-arguments)
  - [Tools with Error Handling](#tools-with-error-handling)
  - [Tools with Authorization Scopes](#tools-with-authorization-scopes)
- [Server State Management](#server-state-management)
- [Request Access](#request-access)
- [Prompts](#prompts)
  - [Basic Prompt Example](#basic-prompt-example)
  - [Prompts Without Arguments](#prompts-without-arguments)
  - [Prompts with Lifespan State](#prompts-with-lifespan-state)
  - [Prompts with Authorization Scopes](#prompts-with-authorization-scopes)
- [STDIO Transport](#stdio-transport)
- [Authentication and Authorization](#authentication-and-authorization)
- [API Reference](#api-reference)
- [License](#license)

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
- **Authorization Scopes**: Support for scope-based authorization using
  Starlette's authentication system.
- **Error Handling**: Tools can optionally return error messages instead of
  raising exceptions.

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

**Constructor Parameters:**

- `name` (str): The name of your MCP server
- `version` (str): The version of your MCP server
- `tools` (tuple[Tool, ...]): Tuple of tools to expose (default: empty tuple)
- `prompts` (tuple[Prompt, ...]): Tuple of prompts to expose (default: empty
  tuple)
- `instructions` (str | None): Optional instructions for AI assistants on how to
  use this server

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
    prompts=my_prompts,
    instructions="Optional instructions for AI assistants on how to use this server"
)

app = Starlette(lifespan=lifespan)
app.mount("/mcp", mcp_server.app)
```

## Tools

Tools are the functions that can be called by the client.

### Basic Tool Example

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

### Tools Without Arguments

You can define tools that don't require any input arguments:

```python
from datetime import UTC, datetime
from pydantic import BaseModel, Field
from http_mcp.types import Tool

class GetTimeOutput(BaseModel):
    time: str = Field(description="The current time")

async def get_time() -> GetTimeOutput:
    """Get the current time."""
    return GetTimeOutput(time=datetime.now(UTC).strftime("%H:%M:%S"))

TOOLS = (
    Tool(
        func=get_time,
        inputs=type(None),  # No arguments required
        output=GetTimeOutput,
    ),
)
```

Alternatively, you can use the `NoArguments` class for better clarity:

```python
from http_mcp.types import Arguments, NoArguments, Tool

class SimpleOutput(BaseModel):
    success: bool = Field(description="Whether the operation was successful")

def simple_tool(args: Arguments[NoArguments]) -> SimpleOutput:
    """A simple tool with no arguments."""
    # You can still access request and state
    context = args.get_state_key("context", Context)
    return SimpleOutput(success=True)

TOOLS = (
    Tool(
        func=simple_tool,
        inputs=NoArguments,
        output=SimpleOutput,
    ),
)
```

### Tools with Error Handling

Tools can optionally return error messages instead of raising exceptions:

```python
from pydantic import BaseModel, Field
from http_mcp.types import Arguments, Tool
from http_mcp.exceptions import ToolInvocationError

class RiskyToolInput(BaseModel):
    value: int = Field(description="An integer value")

class RiskyToolOutput(BaseModel):
    result: str = Field(description="The result of the operation")

def risky_tool(args: Arguments[RiskyToolInput]) -> RiskyToolOutput:
    """A tool that might fail."""
    if args.inputs.value < 0:
        raise ToolInvocationError("risky_tool", "Value must be positive")
    return RiskyToolOutput(result=f"Success: {args.inputs.value}")

TOOLS = (
    Tool(
        func=risky_tool,
        inputs=RiskyToolInput,
        output=RiskyToolOutput,
        return_error_message=True,  # Return ErrorMessage instead of raising
    ),
)
```

When `return_error_message=True`, the tool will return an `ErrorMessage` model
with the error details instead of raising a `ToolInvocationError`.

### Tools with Authorization Scopes

You can restrict tool access based on authentication scopes:

```python
from http_mcp.types import Arguments, NoArguments, Tool
from starlette.authentication import has_required_scope

class SecureOutput(BaseModel):
    message: str = Field(description="A secure message")

def private_tool(args: Arguments[NoArguments]) -> SecureOutput:
    """A tool that requires authentication."""
    assert has_required_scope(args.request, ("private",))
    return SecureOutput(message="This is private data")

def admin_tool(args: Arguments[NoArguments]) -> SecureOutput:
    """A tool that requires admin or superuser scope."""
    assert has_required_scope(args.request, ("admin", "superuser"))
    return SecureOutput(message="This is admin data")

TOOLS = (
    Tool(
        func=private_tool,
        inputs=NoArguments,
        output=SecureOutput,
        scopes=("private",),  # Only accessible with 'private' scope
    ),
    Tool(
        func=admin_tool,
        inputs=NoArguments,
        output=SecureOutput,
        scopes=("admin", "superuser"),  # Accessible with either scope
    ),
)
```

Note: You need to set up authentication middleware in your Starlette app for
scopes to work properly.

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

### Basic Prompt Example

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

### Prompts Without Arguments

You can define prompts that don't require any input arguments:

```python
from http_mcp.mcp_types.content import TextContent
from http_mcp.mcp_types.prompts import PromptMessage
from http_mcp.types import Prompt

def help_prompt() -> tuple[PromptMessage, ...]:
    """Use this prompt to get general help."""
    return (
        PromptMessage(
            role="user",
            content=TextContent(
                text="You are a helpful assistant. Help the user with their task."
            ),
        ),
    )

PROMPTS = (
    Prompt(
        func=help_prompt,
        arguments_type=type(None),  # No arguments required
    ),
)
```

Alternatively, you can use the `NoArguments` class:

```python
from http_mcp.types import Arguments, NoArguments, Prompt
from http_mcp.mcp_types.content import TextContent
from http_mcp.mcp_types.prompts import PromptMessage

def help_prompt_with_context(args: Arguments[NoArguments]) -> tuple[PromptMessage, ...]:
    """Use this prompt to get help with access to context."""
    # You can still access request and state
    context = args.get_state_key("context", Context)
    return (
        PromptMessage(
            role="user",
            content=TextContent(text="You are a helpful assistant."),
        ),
    )

PROMPTS = (
    Prompt(
        func=help_prompt_with_context,
        arguments_type=NoArguments,
    ),
)
```

### Prompts with Lifespan State

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

### Prompts with Authorization Scopes

You can restrict prompt access based on authentication scopes:

```python
from http_mcp.types import Arguments, NoArguments, Prompt
from http_mcp.mcp_types.content import TextContent
from http_mcp.mcp_types.prompts import PromptMessage

def private_prompt(args: Arguments[NoArguments]) -> tuple[PromptMessage, ...]:
    """Private prompt that is only accessible to authenticated users."""
    return (
        PromptMessage(
            role="user",
            content=TextContent(text="This is a private prompt."),
        ),
    )

def admin_prompt(args: Arguments[NoArguments]) -> tuple[PromptMessage, ...]:
    """Admin prompt accessible to users with admin or superuser scope."""
    return (
        PromptMessage(
            role="user",
            content=TextContent(text="This is an admin prompt."),
        ),
    )

PROMPTS = (
    Prompt(
        func=private_prompt,
        arguments_type=NoArguments,
        scopes=("private",),  # Only accessible with 'private' scope
    ),
    Prompt(
        func=admin_prompt,
        arguments_type=NoArguments,
        scopes=("admin", "superuser"),  # Accessible with either scope
    ),
)
```

Note: You need to set up authentication middleware in your Starlette app for
scopes to work properly.

## STDIO Transport

In addition to HTTP transport, the server supports STDIO transport for
communication. This is useful for command-line applications and integrations
that communicate through standard input/output.

### Using STDIO Transport

```python
import asyncio
from http_mcp.server import MCPServer
from app.tools import TOOLS
from app.prompts import PROMPTS

mcp_server = MCPServer(
    tools=TOOLS,
    prompts=PROMPTS,
    name="test",
    version="1.0.0"
)

# Run the server with STDIO transport
async def main() -> None:
    request_headers = {
        "Authorization": "Bearer your-token-here",
        "X-Custom-Header": "value",
    }
    await mcp_server.serve_stdio(request_headers)

asyncio.run(main())
```

The `request_headers` parameter allows you to pass headers that will be included
in the request context, enabling authentication and other header-based features
even when using STDIO transport.

## Authentication and Authorization

The library integrates with Starlette's authentication system to provide
scope-based authorization for tools and prompts.

### Setting Up Authentication Middleware

```python
import contextlib
from collections.abc import AsyncIterator
from typing import TypedDict
from starlette.applications import Starlette
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    BaseUser,
    SimpleUser,
)
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import HTTPConnection

from http_mcp.server import MCPServer
from app.context import Context
from app.tools import TOOLS
from app.prompts import PROMPTS


class BasicAuthBackend(AuthenticationBackend):
    def __init__(self, granted_scopes: tuple[str, ...] = ("authenticated",)) -> None:
        self.granted_scopes = granted_scopes
        super().__init__()

    async def authenticate(
        self, conn: HTTPConnection
    ) -> tuple[AuthCredentials, BaseUser] | None:
        # Implement your authentication logic here
        # For example, check Bearer token, API key, etc.
        auth_header = conn.headers.get("Authorization")
        if not auth_header:
            return None

        # Validate token and return credentials with scopes
        return AuthCredentials(self.granted_scopes), SimpleUser("username")


class State(TypedDict):
    context: Context


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[State]:
    yield {"context": Context()}


mcp_server = MCPServer(
    tools=TOOLS,
    prompts=PROMPTS,
    name="test",
    version="1.0.0"
)

app = Starlette(
    lifespan=lifespan,
    middleware=[
        Middleware(
            AuthenticationMiddleware,
            backend=BasicAuthBackend(granted_scopes=("private", "admin")),
        ),
    ],
)
app.mount("/mcp", mcp_server.app)
```

### How Scopes Work

1. **Authentication Middleware**: The middleware authenticates each request and
   assigns scopes to the user through `AuthCredentials`.

1. **Tool/Prompt Scopes**: When defining tools or prompts, you can specify
   required scopes using the `scopes` parameter.

1. **Access Control**: The server automatically filters tools and prompts based
   on the user's granted scopes. Tools and prompts without the required scopes
   are not visible in listings and cannot be invoked.

1. **Multiple Scopes**: If you specify multiple scopes (e.g.,
   `scopes=("admin", "superuser")`), the user needs at least one of those scopes
   to access the tool or prompt.

## API Reference

### Tool Class

The `Tool` class is used to define tools that can be invoked by clients.

**Parameters:**

- `func`: The function to be invoked. Can be sync or async. The function can
  either:
  - Accept an `Arguments[TInputs]` parameter
  - Accept no parameters
- `inputs`: The Pydantic model class for input validation. Use `type(None)` or
  `NoArguments` for tools without inputs
- `output`: The Pydantic model class for output validation
- `return_error_message` (bool): If `True`, tool errors return `ErrorMessage`
  instead of raising exceptions (default: `False`)
- `scopes` (tuple[str, ...]): Required authentication scopes for accessing this
  tool (default: empty tuple)

**Properties:**

- `name`: The function name (derived from `func.__name__`)
- `title`: A human-readable title (derived from the function name)
- `description`: The function's docstring
- `input_schema`: JSON schema for the input parameters
- `output_schema`: JSON schema for the output

### Prompt Class

The `Prompt` class is used to define prompts that can be invoked by clients.

**Parameters:**

- `func`: The function to be invoked. Can be sync or async. The function can
  either:
  - Accept an `Arguments[TArguments]` parameter
  - Accept no parameters
  - Must return `tuple[PromptMessage, ...]`
- `arguments_type`: The Pydantic model class for argument validation. Use
  `type(None)` or `NoArguments` for prompts without arguments
- `scopes` (tuple[str, ...]): Required authentication scopes for accessing this
  prompt (default: empty tuple)

**Properties:**

- `name`: The function name (derived from `func.__name__`)
- `title`: A human-readable title (derived from the function name)
- `description`: The function's docstring
- `arguments`: Tuple of `PromptArgument` objects defining the prompt's arguments

### Arguments Class

The `Arguments` class is passed to tool and prompt functions to provide access
to inputs, request, and state.

**Parameters:**

- `request`: The Starlette `Request` object
- `inputs`: The validated input/argument data (type depends on the Tool/Prompt
  definition)

**Methods:**

- `get_state_key(key: str, _object_type: type[TKey]) -> TKey`: Access a value
  from the lifespan state. Raises `ServerError` if the key doesn't exist.

### NoArguments Class

An empty Pydantic model that can be used as a clearer alternative to
`type(None)` when defining tools or prompts without arguments.

```python
from http_mcp.types import NoArguments

# Use this instead of type(None)
Tool(func=my_func, inputs=NoArguments, output=MyOutput)
```

## Installation

Install the package using pip or uv:

```bash
pip install http-mcp
```

or

```bash
uv add http-mcp
```

## License

This project is licensed under the MIT License. See the LICENSE file for
details.
