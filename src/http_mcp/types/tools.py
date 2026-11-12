import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, assert_never, cast

from pydantic import BaseModel
from starlette.requests import Request

from http_mcp._mcp_types.tools import ToolAnnotations
from http_mcp._parsing import InvalidModel, Parsed, parse_model
from http_mcp.exceptions import ServerError, ToolInvocationError
from http_mcp.failures import (
    InvalidArguments,
    StructuredToolInvocationFailed,
    ToolInvocationFailed,
    tool_failure_message,
)
from http_mcp.types.continuation import InvocationResult
from http_mcp.types.models import Arguments, ErrorMessage
from http_mcp.types.utils import generate_union_schema

LOGGER = logging.getLogger(__name__)


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

        return_error_message: If True, a failed invocation includes ErrorMessage structured
        data. Both modes report failures with `isError` set.

        scopes: Works the same as starlette's scope. Is used to exposed tools given authorization
        scopes.

        annotations: Explicit tool hints. Unspecified safety hints are omitted.

    """

    func: (
        Callable[
            [Arguments[TInputs]],
            Awaitable[InvocationResult[TOutput]] | InvocationResult[TOutput],
        ]
        | Callable[
            [],
            Awaitable[InvocationResult[TOutput]] | InvocationResult[TOutput],
        ]
    )
    inputs: type[TInputs]
    output: type[TOutput]
    return_error_message: bool = False
    scopes: tuple[str, ...] = ()
    annotations: ToolAnnotations = field(default_factory=ToolAnnotations)

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

            schema = EmptyInput.model_json_schema(by_alias=True, mode="validation")
        else:
            schema = self.inputs.model_json_schema(by_alias=True, mode="validation")
        schema["title"] = self.name + "Arguments"
        return schema

    @property
    def output_schema(self) -> dict:
        if self.return_error_message:
            schema = generate_union_schema(self.output, ErrorMessage)
        else:
            schema = self.output.model_json_schema(by_alias=True, mode="serialization")
        schema["title"] = self.name + "Output"
        return schema

    async def _run_without_arguments(self) -> InvocationResult[TOutput]:
        if inspect.iscoroutinefunction(self.func):
            return await self.func()

        return await asyncio.to_thread(
            cast(
                "Callable[[], InvocationResult[TOutput]]",
                self.func,
            ),
        )

    async def _run_with_arguments(
        self,
        arguments: Arguments[TInputs],
    ) -> InvocationResult[TOutput]:
        if inspect.iscoroutinefunction(self.func):
            return await self.func(arguments)

        _func = cast(
            "Callable[[Arguments[TInputs]], InvocationResult[TOutput]]",
            self.func,
        )
        return await asyncio.to_thread(_func, arguments)

    async def _contain(
        self,
        run: Coroutine[Any, Any, InvocationResult[TOutput]],
    ) -> InvocationResult[TOutput] | StructuredToolInvocationFailed | ToolInvocationFailed:
        """Run the tool function, turning anything it raises into a value.

        Tool functions are user code and may raise anything, so this is the boundary
        where exceptions stop.
        """
        try:
            return await run
        except ToolInvocationError as e:
            LOGGER.exception("Error calling tool %s", self.name)
            return self._failure(e.message)
        except ServerError as e:
            LOGGER.exception("Error calling tool %s", self.name)
            return self._failure(e.message)
        except Exception:
            LOGGER.exception("Error calling tool %s", self.name)
            message = tool_failure_message(self.name, "Unknown error")
            return self._failure(message)

    def _failure(self, message: str) -> StructuredToolInvocationFailed | ToolInvocationFailed:
        if self.return_error_message:
            return StructuredToolInvocationFailed(message)
        return ToolInvocationFailed(message)

    async def invoke(
        self,
        args: dict,
        request: Request,
    ) -> (
        InvocationResult[TOutput]
        | StructuredToolInvocationFailed
        | InvalidArguments
        | ToolInvocationFailed
    ):
        # Handle functions without arguments
        if issubclass(self.inputs, type(None)):
            return await self._contain(self._run_without_arguments())

        match parse_model(self.inputs, args):
            case InvalidModel(description=description):
                return InvalidArguments("tool", self.name, description)
            case Parsed(value=validated_args):
                arguments = Arguments[TInputs](request, validated_args)
                return await self._contain(self._run_with_arguments(arguments))
            case _ as unreachable:
                assert_never(unreachable)

    def generate_json_schema(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "annotations": {
                "title": self.title,
                **self.annotations.model_dump(by_alias=True, exclude_none=True),
            },
        }
