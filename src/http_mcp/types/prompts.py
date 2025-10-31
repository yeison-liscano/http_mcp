import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel, ValidationError
from starlette.requests import Request

from http_mcp.exceptions import ArgumentsError, PromptInvocationError, ServerError
from http_mcp.mcp_types.prompts import PromptArgument, PromptMessage, ProtocolPrompt
from http_mcp.types import Arguments


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

    async def invoke(
        self,
        arguments: dict,
        request: Request,
    ) -> tuple[PromptMessage, ...]:
        # Handle functions without arguments
        if issubclass(self.arguments_type, type(None)):
            try:
                if inspect.iscoroutinefunction(self.func):
                    return await self.func()

                return await asyncio.to_thread(
                    cast(
                        "Callable[[], tuple[PromptMessage, ...]]",
                        self.func,
                    ),
                )
            except ServerError:
                raise
            except Exception as e:
                raise PromptInvocationError(self.name, "Unknown error") from e

        # Handle functions with arguments
        try:
            _arguments = self.arguments_type.model_validate(arguments)
        except ValidationError as e:
            raise ArgumentsError("prompt", self.name, e.json()) from e

        try:
            if inspect.iscoroutinefunction(self.func):
                return await self.func(Arguments(request, _arguments))

            _func = cast(
                "Callable[[Arguments[TArguments]], tuple[PromptMessage, ...]]",
                self.func,
            )
            return await asyncio.to_thread(_func, Arguments(request, _arguments))
        except ServerError:
            raise
        except Exception as e:
            raise PromptInvocationError(self.name, "Unknown error") from e
