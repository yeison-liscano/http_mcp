import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from pydantic import BaseModel, ValidationError
from starlette.requests import Request

from http_mcp.exceptions import ArgumentsError, ToolInvocationError

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
    func: Callable[
        [ToolArguments[TArguments_co, TToolsContext]], Awaitable[TOutput_co] | TOutput_co,
    ]
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

    async def invoke(
        self,
        args: dict,
        request: Request,
        context: TToolsContext,
    ) -> TOutput_co:
        try:
            validated_args = self.input.model_validate(args)
        except ValidationError as e:
            raise ArgumentsError("tool", self.name, e.json()) from e

        try:
            _args = ToolArguments(request, validated_args, context)
            if inspect.iscoroutinefunction(self.func):
                return await self.func(_args)

            _func = cast(
                Callable[[ToolArguments[TArguments_co, TToolsContext]], TOutput_co], self.func,
            )
            return await asyncio.to_thread(_func, _args)
        except Exception as e:
            raise ToolInvocationError(self.name, "Unknown error") from e

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
