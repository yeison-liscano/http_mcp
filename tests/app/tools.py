from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from starlette.authentication import has_required_scope

from http_mcp.types import Arguments, NoArguments, Tool
from tests.app.context import Context


class GetWeatherInput(BaseModel):
    location: str = Field(description="The location to get the weather for")
    unit: str = Field(description="The unit of temperature", default="celsius")


class GetWeatherOutput(BaseModel):
    weather: str = Field(description="The weather in the given location")


class SimpleOutput(BaseModel):
    success: bool = Field(description="Whether the operation was successful", default=True)


async def get_weather(args: Arguments[GetWeatherInput]) -> GetWeatherOutput:
    """Get the current weather in a given location."""
    args.get_state_key("context", Context).add_called_tool("get_weather")
    return GetWeatherOutput(
        weather=f"The weather in {args.inputs.location} is 25 degrees {args.inputs.unit}",
    )


class GetTimeOutput(BaseModel):
    time: str = Field(description="The current time")


async def get_time() -> GetTimeOutput:
    """Get the current time."""
    return GetTimeOutput(time=datetime.now(UTC).strftime("%H:%M:%S"))


class ToolThatAccessRequest(BaseModel):
    username: str = Field(description="The username of the user")


class ToolThatAccessRequestOutput(BaseModel):
    message: str = Field(description="The message to the user")


async def tool_that_access_request(
    args: Arguments[ToolThatAccessRequest],
) -> ToolThatAccessRequestOutput:
    """Access the request."""
    test_header = args.request.headers.get("X-TEST-HEADER")
    args.get_state_key("context", Context).add_called_tool("tool_that_access_request")
    return ToolThatAccessRequestOutput(
        message=f"Hello {args.inputs.username} you are authenticated with {test_header}",
    )


def private_tool(args: Arguments[NoArguments]) -> SimpleOutput:
    """Private tool that is only accessible to authenticated users."""
    assert has_required_scope(args.request, ("private",))

    args.get_state_key("context", Context).add_called_tool("private_tool")
    return SimpleOutput(success=True)


async def private_multi_scope_tool(args: Arguments[NoArguments]) -> SimpleOutput:
    """Private tool that.

    Can be accessed by authenticated users with the 'private' or 'superuser' scopes.
    """
    assert has_required_scope(args.request, ("private", "superuser"))

    args.get_state_key("context", Context).add_called_tool("private_multi_scope_tool")
    return SimpleOutput(success=True)


class GetCalledToolsInput(BaseModel):
    pass


class GetCalledToolsOutput(BaseModel):
    called_tools: list[str] = Field(description="The list of called tools")


async def get_called_tools(
    args: Arguments[GetCalledToolsInput],
) -> GetCalledToolsOutput:
    """Get the list of called tools."""
    context = args.get_state_key("context", Context)
    return GetCalledToolsOutput(called_tools=context.get_called_tools())


TOOLS = (
    Tool(
        func=get_weather,
        inputs=GetWeatherInput,
        output=GetWeatherOutput,
    ),
    Tool(
        func=get_time,
        inputs=type(None),
        output=GetTimeOutput,
    ),
    Tool(
        func=tool_that_access_request,
        inputs=ToolThatAccessRequest,
        output=ToolThatAccessRequestOutput,
    ),
    Tool(
        func=get_called_tools,
        inputs=GetCalledToolsInput,
        output=GetCalledToolsOutput,
    ),
    Tool(
        func=private_tool,
        inputs=NoArguments,
        output=SimpleOutput,
        scopes=("private",),
    ),
    Tool(
        func=private_multi_scope_tool,
        inputs=NoArguments,
        output=SimpleOutput,
        scopes=("private", "superuser"),
    ),
)
