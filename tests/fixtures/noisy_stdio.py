"""A STDIO server whose tool writes to stdout, as careless tool code does."""

import asyncio

from pydantic import BaseModel

from http_mcp.server import MCPServer
from http_mcp.types import Arguments, Tool


class EchoInput(BaseModel):
    text: str


class EchoOutput(BaseModel):
    text: str


def echo(args: Arguments[EchoInput]) -> EchoOutput:
    """Echo the input, printing it on the way."""
    print(args.inputs.text)  # noqa: T201
    return EchoOutput(text=args.inputs.text)


server = MCPServer(
    name="noisy",
    version="1.0.0",
    tools=(Tool(func=echo, inputs=EchoInput, output=EchoOutput),),
)


def run() -> None:
    asyncio.run(server.serve_stdio())
