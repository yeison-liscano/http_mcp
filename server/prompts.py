from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel

from server.mcp_types.prompts import PromptArgument, PromptMessage, ProtocolPrompt

TArguments = TypeVar("TArguments", bound=BaseModel)


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
