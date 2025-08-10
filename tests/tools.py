from pydantic import BaseModel

from server.models import Input, Tool


class TestToolArguments(BaseModel):
    question: str


class TestToolOutput(BaseModel):
    answer: str


async def simple_server_tool(args: Input[TestToolArguments, None]) -> TestToolOutput:
    """Return a simple server tool."""
    assert args.arguments.question == "What is the meaning of life?"
    assert args.request.method == "POST"
    assert args.context is None
    return TestToolOutput(answer=f"Hello, {args.arguments.question}!")


TOOLS = (
    Tool(
        func=simple_server_tool,
        input=Input[TestToolArguments, None],
        input_arguments=TestToolArguments,
        output=TestToolOutput,
    ),
)
