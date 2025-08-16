from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from server.content import TextContent
from server.messages import JSONRPCMessage, JSONRPCRequest

TArguments = TypeVar("TArguments", bound=BaseModel)


class PromptGetRequestParams(BaseModel):
    name: str
    arguments: dict


class PromptGetRequest(JSONRPCRequest):
    method: Literal["prompts/get"]
    params: PromptGetRequestParams


class PromptListRequestParams(BaseModel):
    cursor: str | None = None


class PromptListRequest(JSONRPCRequest):
    method: Literal["prompts/list"]


class PromptArgument(BaseModel):
    name: str = Field(description="The name of the argument")
    description: str
    required: bool


class ProtocolPrompt(BaseModel):
    name: str
    title: str
    description: str
    arguments: tuple[PromptArgument, ...]


class PromptListResult(BaseModel):
    prompts: tuple[ProtocolPrompt, ...]
    next_cursor: str | None = Field(
        serialization_alias="nextCursor", alias_priority=1, default=None
    )


class PromptsListResponse(JSONRPCMessage):
    result: PromptListResult


class PromptMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: TextContent


class PromptGetResult(BaseModel):
    description: str
    messages: tuple[PromptMessage, ...]


class PromptsGetResponse(JSONRPCMessage):
    result: PromptGetResult


@dataclass
class Prompt(Generic[TArguments]):
    func: Callable[[TArguments], Awaitable[tuple[PromptMessage, ...]] | tuple[PromptMessage, ...]]
    arguments_type: type[TArguments]

    @property
    def arguments(self) -> tuple[PromptArgument, ...]:
        schema = self.arguments_type.model_json_schema()

        required = schema["required"]

        return tuple(
            PromptArgument(
                name=name,
                description=values.get("description", name.title()),
                required=name in required,
            )
            for name, values in self.arguments_type.model_json_schema()["properties"].items()
        )

    @property
    def name(self) -> str:
        return self.func.__name__

    @property
    def title(self) -> str:
        return self.name.replace("_", " ").title()

    @property
    def description(self) -> str:
        return self.func.__doc__ or self.title

    def to_prompt_protocol_object(self) -> ProtocolPrompt:
        return ProtocolPrompt(
            name=self.name,
            title=self.title,
            description=self.description,
            arguments=self.arguments,
        )


def main_1() -> None:
    schema = PromptArgument.model_json_schema()

    required = schema["required"]

    _ = [
        {
            "name": name,
            "description": values.get("description", name.title()),
            "required": name in required,
        }
        for name, values in schema["properties"].items()
    ]


class TestArguments(BaseModel):
    argument_1: int = Field(description="The first argument")
    argument_2: str = Field(description="The second argument")
    argument_3: bool = Field(description="The third argument")
    argument_4: float = Field(description="The fourth argument")


def main() -> None:
    _ = Prompt(
        func=lambda _: (PromptMessage(role="user", content=TextContent(text="test")),),
        arguments_type=TestArguments,
    ).arguments
