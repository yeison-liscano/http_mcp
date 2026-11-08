import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Any, assert_never, cast

from pydantic import BaseModel
from starlette.requests import Request

from http_mcp._mcp_types.prompts import (
    PromptArgument,
    PromptMessage,
    ProtocolPrompt,
    RenderedPrompt,
)
from http_mcp._parsing import InvalidModel, Parsed, parse_model
from http_mcp.exceptions import PromptInvocationError, ServerError
from http_mcp.failures import (
    InvalidArguments,
    PromptInvocationFailed,
    PromptServerFailure,
    prompt_failure_message,
)
from http_mcp.types import Arguments

LOGGER = logging.getLogger(__name__)


@dataclass
class Prompt[TArguments: BaseModel | None]:
    func: (
        Callable[
            [Arguments[TArguments]],
            Awaitable[tuple[PromptMessage, ...]] | tuple[PromptMessage, ...],
        ]
        | Callable[
            [],
            Awaitable[tuple[PromptMessage, ...]] | tuple[PromptMessage, ...],
        ]
    )
    arguments_type: type[TArguments]
    scopes: tuple[str, ...] = ()

    @property
    def arguments(self) -> tuple[PromptArgument, ...]:
        if issubclass(self.arguments_type, type(None)):
            return ()

        schema = self.arguments_type.model_json_schema()

        required = schema.get("required", [])

        return tuple(
            PromptArgument(
                name=name,
                description=values.get("description", name.title()),
                required=name in required,
            )
            for name, values in schema["properties"].items()
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

    async def _run_without_arguments(self) -> tuple[PromptMessage, ...]:
        if inspect.iscoroutinefunction(self.func):
            return await self.func()

        return await asyncio.to_thread(
            cast(
                "Callable[[], tuple[PromptMessage, ...]]",
                self.func,
            ),
        )

    async def _run_with_arguments(
        self,
        arguments: Arguments[TArguments],
    ) -> tuple[PromptMessage, ...]:
        if inspect.iscoroutinefunction(self.func):
            return await self.func(arguments)

        _func = cast(
            "Callable[[Arguments[TArguments]], tuple[PromptMessage, ...]]",
            self.func,
        )
        return await asyncio.to_thread(_func, arguments)

    async def _contain(
        self,
        run: Coroutine[Any, Any, tuple[PromptMessage, ...]],
    ) -> RenderedPrompt | PromptInvocationFailed | PromptServerFailure:
        """Run the prompt function, turning anything it raises into a value.

        Prompt functions are user code and may raise anything, so this is the boundary
        where exceptions stop.
        """
        try:
            messages = await run
        except PromptInvocationError as e:
            return PromptInvocationFailed(e.message)
        except ServerError as e:
            return PromptServerFailure(e.error.code, e.message)
        except Exception:
            LOGGER.exception("Error getting prompt %s", self.name)
            return PromptInvocationFailed(prompt_failure_message(self.name, "Unknown error"))
        return RenderedPrompt(description=self.description, messages=messages)

    async def invoke(
        self,
        arguments: dict,
        request: Request,
    ) -> RenderedPrompt | InvalidArguments | PromptInvocationFailed | PromptServerFailure:
        # Handle functions without arguments
        if issubclass(self.arguments_type, type(None)):
            return await self._contain(self._run_without_arguments())

        # Handle functions with arguments
        match parse_model(self.arguments_type, arguments):
            case InvalidModel(description=description):
                return InvalidArguments("prompt", self.name, description)
            case Parsed(value=validated_arguments):
                return await self._contain(
                    self._run_with_arguments(Arguments(request, validated_arguments)),
                )
            case _ as unreachable:
                assert_never(unreachable)
