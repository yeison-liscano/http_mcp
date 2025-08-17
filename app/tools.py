from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from http_mcp.tools import Tool, ToolArguments


@dataclass
class Context:
    called_tools: list[str] = field(default_factory=list)

    def get_called_tools(self) -> list[str]:
        return self.called_tools

    def add_called_tool(self, tool_name: str) -> None:
        self.called_tools.append(tool_name)


class GetWeatherInput(BaseModel):
    location: str = Field(description="The location to get the weather for")
    unit: str = Field(description="The unit of temperature", default="celsius")


class GetWeatherOutput(BaseModel):
    weather: str = Field(description="The weather in the given location")


async def get_weather(args: ToolArguments[GetWeatherInput, Context]) -> GetWeatherOutput:
    """Get the current weather in a given location."""
    args.context.add_called_tool("get_weather")
    return GetWeatherOutput(
        weather=f"The weather in {args.inputs.location} is 25 degrees {args.inputs.unit}",
    )


class GetTimeInput(BaseModel):
    pass


class GetTimeOutput(BaseModel):
    time: str = Field(description="The current time")


async def get_time(args: ToolArguments[GetTimeInput, Context]) -> GetTimeOutput:
    """Get the current time."""
    args.context.add_called_tool("get_time")
    return GetTimeOutput(time=datetime.now(UTC).strftime("%H:%M:%S"))


class ToolThatAccessRequest(BaseModel):
    username: str = Field(description="The username of the user")


class ToolThatAccessRequestOutput(BaseModel):
    message: str = Field(description="The message to the user")


async def tool_that_access_request(
    args: ToolArguments[ToolThatAccessRequest, Context],
) -> ToolThatAccessRequestOutput:
    """Access the request."""
    req_authentication = args.request.headers.get("Authorization")
    args.context.add_called_tool("tool_that_access_request")
    return ToolThatAccessRequestOutput(
        message=f"Hello {args.inputs.username} you are authenticated with {req_authentication}",
    )


class GetCalledToolsInput(BaseModel):
    pass


class GetCalledToolsOutput(BaseModel):
    called_tools: list[str] = Field(description="The list of called tools")


async def get_called_tools(
    args: ToolArguments[GetCalledToolsInput, Context],
) -> GetCalledToolsOutput:
    """Get the list of called tools."""
    return GetCalledToolsOutput(called_tools=args.context.get_called_tools())


TOOLS = (
    Tool(
        func=get_weather,
        input=GetWeatherInput,
        output=GetWeatherOutput,
    ),
    Tool(
        func=get_time,
        input=GetTimeInput,
        output=GetTimeOutput,
    ),
    Tool(
        func=tool_that_access_request,
        input=ToolThatAccessRequest,
        output=ToolThatAccessRequestOutput,
    ),
    Tool(
        func=get_called_tools,
        input=GetCalledToolsInput,
        output=GetCalledToolsOutput,
    ),
)
