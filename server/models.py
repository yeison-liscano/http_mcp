from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, Field
from starlette.requests import Request

TToolsContext = TypeVar("TToolsContext")
TToolsArguments_co = TypeVar("TToolsArguments_co", bound=BaseModel, covariant=True)
TToolsOutput_co = TypeVar("TToolsOutput_co", bound=BaseModel, covariant=True)


@dataclass
class ToolArguments(Generic[TToolsArguments_co, TToolsContext]):
    request: Request
    inputs: TToolsArguments_co
    context: TToolsContext


@dataclass
class Tool(Generic[TToolsArguments_co, TToolsContext, TToolsOutput_co]):
    func: Callable[[ToolArguments[TToolsArguments_co, TToolsContext]], Awaitable[TToolsOutput_co]]
    input: type[TToolsArguments_co]
    output: type[TToolsOutput_co]

    @property
    def annotations(self) -> Mapping[str, str | bool]:
        return {
            "title": self.title,
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        }

    @property
    def name(self) -> str:
        return self.func.__name__

    @property
    def title(self) -> str:
        return self.func.__name__.replace("_", " ").title()

    @property
    def description(self) -> str:
        return self.func.__doc__ or "No description"

    @property
    def input_schema(self) -> dict:
        schema = self.input.model_json_schema()
        schema["title"] = self.name + "Arguments"
        return schema

    @property
    def output_schema(self) -> dict:
        schema = self.output.model_json_schema()
        schema["title"] = self.name + "Output"
        return schema

    async def invoque(
        self,
        args: dict,
        request: Request,
        context: TToolsContext,
    ) -> TToolsOutput_co:
        validated_args = self.input.model_validate(args)
        return await self.func(ToolArguments(request, validated_args, context))

    def generate_json_schema(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "annotations": self.annotations,
            "meta": None,
        }


class Capability(BaseModel):
    list_changed: bool = Field(serialization_alias="listChanged", alias_priority=1)
    subscribe: bool = Field(serialization_alias="subscribe", alias_priority=1)


class ServerCapabilities(BaseModel):
    prompts: Capability | None = None
    tools: Capability | None = None
