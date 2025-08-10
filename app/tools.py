from datetime import UTC, datetime

from pydantic import BaseModel, Field

from server.models import Input, Tool


class GetWeatherInput(BaseModel):
    location: str = Field(description="The location to get the weather for")
    unit: str = Field(description="The unit of temperature", default="celsius")


class GetWeatherOutput(BaseModel):
    weather: str = Field(description="The weather in the given location")


async def get_weather(args: Input[GetWeatherInput, None]) -> GetWeatherOutput:
    """Get the current weather in a given location."""
    return GetWeatherOutput(
        weather=f"The weather in {args.arguments.location} is 25 degrees {args.arguments.unit}"
    )


class GetTimeInput(BaseModel):
    pass


class GetTimeOutput(BaseModel):
    time: str = Field(description="The current time")


async def get_time(_args: Input[GetTimeInput, None]) -> GetTimeOutput:
    """Get the current time."""
    return GetTimeOutput(time=datetime.now(UTC).strftime("%H:%M:%S"))


TOOLS = (
    Tool(
        func=get_weather,
        input=Input[GetWeatherInput, None],
        input_arguments=GetWeatherInput,
        output=GetWeatherOutput,
    ),
    Tool(
        func=get_time,
        input=Input[GetTimeInput, None],
        input_arguments=GetTimeInput,
        output=GetTimeOutput,
    ),
)
