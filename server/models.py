from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel
from starlette.requests import Request

TToolsContext = TypeVar("TToolsContext", bound=BaseModel | None)
TToolsArguments_co = TypeVar("TToolsArguments_co", bound=BaseModel, covariant=True)
TToolsOutput_co = TypeVar("TToolsOutput_co", bound=BaseModel, covariant=True)


@dataclass
class Input(Generic[TToolsArguments_co, TToolsContext]):
    request: Request
    arguments: TToolsArguments_co
    context: TToolsContext | None = None


@dataclass
class Tool(Generic[TToolsArguments_co, TToolsContext, TToolsOutput_co]):
    func: Callable[[Input[TToolsArguments_co, TToolsContext]], Awaitable[TToolsOutput_co]]
    input: type[Input[TToolsArguments_co, TToolsContext]]
    input_arguments: type[TToolsArguments_co]
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
        schema = self.input_arguments.model_json_schema()
        schema["title"] = self.name + "Arguments"
        return schema

    @property
    def output_schema(self) -> dict:
        schema = self.output.model_json_schema()
        schema["title"] = self.name + "Output"
        return schema

    async def invoque(
        self, args: dict, request: Request, context: TToolsContext
    ) -> TToolsOutput_co:
        validated_args = self.input_arguments.model_validate(args)
        return await self.func(self.input(request, validated_args, context))

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
