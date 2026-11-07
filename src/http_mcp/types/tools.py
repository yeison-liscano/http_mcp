import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from typing import Any, assert_never, cast

from pydantic import BaseModel
from starlette.requests import Request

from http_mcp._parsing import InvalidModel, Parsed, parse_model
from http_mcp.exceptions import ServerError, ToolInvocationError
from http_mcp.failures import InvalidArguments, ToolInvocationFailed, tool_failure_message
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

        return_error_message: If True, a failed invocation produces an ErrorMessage as the output
        of the tool. If False (default), it is reported as a result with `isError` set.

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

    async def _run_without_arguments(self) -> TOutput:
        if inspect.iscoroutinefunction(self.func):
            return await self.func()

        return await asyncio.to_thread(
            cast(
                "Callable[[], TOutput]",
                self.func,
            ),
        )

    async def _run_with_arguments(self, arguments: Arguments[TInputs]) -> TOutput:
        if inspect.iscoroutinefunction(self.func):
            return await self.func(arguments)

        _func = cast(
            "Callable[[Arguments[TInputs]], TOutput]",
            self.func,
        )
        return await asyncio.to_thread(_func, arguments)

    async def _contain(
        self,
        run: Coroutine[Any, Any, TOutput],
    ) -> TOutput | ErrorMessage | ToolInvocationFailed:
        """Run the tool function, turning anything it raises into a value.

        Tool functions are user code and may raise anything, so this is the boundary
        where exceptions stop.
        """
        try:
            return await run
        except ToolInvocationError as e:
            if self.return_error_message:
                return ErrorMessage(error_message=e.message)
            LOGGER.exception("Error calling tool %s", self.name)
            return ToolInvocationFailed(e.message)
        except ServerError as e:
            LOGGER.exception("Error calling tool %s", self.name)
            return ToolInvocationFailed(e.message)
        except Exception:
            LOGGER.exception("Error calling tool %s", self.name)
            message = tool_failure_message(self.name, "Unknown error")
            if self.return_error_message:
                return ErrorMessage(error_message=message)
            return ToolInvocationFailed(message)

    async def invoke(
        self,
        args: dict,
        request: Request,
    ) -> TOutput | ErrorMessage | InvalidArguments | ToolInvocationFailed:
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
            "annotations": self.annotations,
        }
