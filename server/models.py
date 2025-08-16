from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel
from starlette.requests import Request

from server.content import TextContent
from server.prompts import PromptArgument, ProtocolPrompt

TToolsContext = TypeVar("TToolsContext")
TArguments_co = TypeVar("TArguments_co", bound=BaseModel, covariant=True)
TOutput_co = TypeVar("TOutput_co", bound=BaseModel, covariant=True)


@dataclass
class ToolArguments(Generic[TArguments_co, TToolsContext]):
    request: Request
    inputs: TArguments_co
    context: TToolsContext


@dataclass
class Tool(Generic[TArguments_co, TToolsContext, TOutput_co]):
    func: Callable[[ToolArguments[TArguments_co, TToolsContext]], Awaitable[TOutput_co]]
    input: type[TArguments_co]
    output: type[TOutput_co]

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
    ) -> TOutput_co:
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


@dataclass
class Prompt(Generic[TArguments_co]):
    func: Callable[[TArguments_co], Awaitable[TextContent] | TextContent]
    arguments: type[TArguments_co]

    @property
    def title(self) -> str:
        return self.name.replace("_", " ").title()

    @property
    def description(self) -> str:
        return self.arguments.model_json_schema()["description"]

    @property
    def name(self) -> str:
        return self.func.__name__

    def to_prompt_protocol_object(self) -> ProtocolPrompt:
        return ProtocolPrompt(
            name=self.name,
            title=self.title,
            description=self.description,
            arguments=tuple(
                PromptArgument(
                    name=arg.name,
                    description=arg.description,
                    required=arg.required,
                )
                for arg in self.arguments.model_json_schema()["properties"].values()
            ),
        )

