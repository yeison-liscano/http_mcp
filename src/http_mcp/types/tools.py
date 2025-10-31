import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel, ValidationError
from starlette.requests import Request

from http_mcp.exceptions import ArgumentsError, ServerError, ToolInvocationError
from http_mcp.types.models import Arguments, ErrorMessage
from http_mcp.types.utils import generate_union_schema


@dataclass
class Tool[TInputs: BaseModel | None, TOutput: BaseModel]:
    """Represents a tool that can be invoked with validated arguments.

    Attributes:
        func: The function to be invoked when the tool is called. Can be either:
            - A function that accepts Arguments[TInputs] parameter
            - A function that accepts no parameters
            Both sync and async functions are supported.

        inputs: The Pydantic model class that defines and validates the input schema.
            Use None if the tool accepts no arguments.

        output: The Pydantic model class that defines the output schema.
            This model is used to generate the tool's output schema.

        return_error_message: If True, any ToolInvocationError will be caught and the ErrorMessage
        will be returned instead of returning a JSONRPCError.
        If False (default), returns the raw output model directly or raises a ToolInvocationError.

        scopes: Works the same as starlette's scope. Is used to exposed tools given authorization
        scopes.

    """

    func: (
        Callable[
            [Arguments[TInputs]],
            Awaitable[TOutput] | TOutput,
        ]
        | Callable[
            [],
            Awaitable[TOutput] | TOutput,
        ]
    )
    inputs: type[TInputs]
    output: type[TOutput]
    return_error_message: bool = False
    scopes: tuple[str, ...] = ()

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
        if issubclass(self.inputs, type(None)):

            class EmptyInput(BaseModel):
                pass

            schema = EmptyInput.model_json_schema(by_alias=False)
        else:
            schema = self.inputs.model_json_schema(by_alias=False)
        schema["title"] = self.name + "Arguments"
        return schema

    @property
    def output_schema(self) -> dict:
        if self.return_error_message:
            schema = generate_union_schema(self.output, ErrorMessage)
        else:
            schema = self.output.model_json_schema(by_alias=False)
        schema["title"] = self.name + "Output"
        return schema

    async def _invoke(
        self,
        args: dict,
        request: Request,
    ) -> TOutput:
        # Handle functions without arguments
        if issubclass(self.inputs, type(None)):
            try:
                if inspect.iscoroutinefunction(self.func):
                    return await self.func()

                return await asyncio.to_thread(
                    cast(
                        "Callable[[], TOutput]",
                        self.func,
                    ),
                )
            except ServerError:
                raise
            except Exception as e:
                raise ToolInvocationError(self.name, "Unknown error") from e

        try:
            validated_args = self.inputs.model_validate(args)
        except ValidationError as e:
            raise ArgumentsError("tool", self.name, e.json()) from e

        try:
            _args = Arguments[TInputs](request, validated_args)
            if inspect.iscoroutinefunction(self.func):
                return await self.func(_args)

            _func = cast(
                "Callable[[Arguments[TInputs]], TOutput]",
                self.func,
            )
            return await asyncio.to_thread(_func, _args)
        except ServerError:
            raise
        except Exception as e:
            raise ToolInvocationError(self.name, "Unknown error") from e

    async def invoke(
        self,
        args: dict,
        request: Request,
    ) -> TOutput | ErrorMessage:
        try:
            return await self._invoke(args, request)
        except ToolInvocationError as e:
            if self.return_error_message:
                return ErrorMessage(error_message=e.message)
            raise

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
