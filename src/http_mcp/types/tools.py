import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from pydantic import BaseModel, ValidationError
from starlette.requests import Request

from http_mcp.exceptions import ArgumentsError, ToolInvocationError
from http_mcp.types.models import Arguments

_TArguments_contra = TypeVar("_TArguments_contra", bound=BaseModel, contravariant=True)
_TOutput_contra = TypeVar("_TOutput_contra", bound=BaseModel, contravariant=True)


@dataclass
class Tool(Generic[_TArguments_contra, _TOutput_contra]):
    func: Callable[
        [Arguments[_TArguments_contra]],
        Awaitable[_TOutput_contra] | _TOutput_contra,
    ]
    inputs: type[_TArguments_contra]
    output: type[_TOutput_contra]

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
        schema = self.inputs.model_json_schema()
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
    ) -> _TOutput_contra:
        try:
            validated_args = self.inputs.model_validate(args)
        except ValidationError as e:
            raise ArgumentsError("tool", self.name, e.json()) from e

        try:
            _args = Arguments(request, validated_args)
            if inspect.iscoroutinefunction(self.func):
                return await self.func(_args)

            _func = cast(
                "Callable[[Arguments[_TArguments_contra]], _TOutput_contra]",
                self.func,
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
