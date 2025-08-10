from datetime import UTC, datetime

from pydantic import BaseModel

from server.models import Input, Tool


class GetWeatherInput(BaseModel):
    location: str
    unit: str = "celsius"


class GetWeatherOutput(BaseModel):
    weather: str


async def get_weather(args: Input[GetWeatherInput, None]) -> GetWeatherOutput:
    """Get the current weather in a given location."""
    return GetWeatherOutput(
        weather=f"The weather in {args.arguments.location} is 25 degrees {args.arguments.unit}"
    )


class GetTimeInput(BaseModel):
    pass


class GetTimeOutput(BaseModel):
    time: str


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
