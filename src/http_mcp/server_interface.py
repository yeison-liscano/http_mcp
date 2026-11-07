from abc import ABC, abstractmethod

from pydantic import BaseModel
from starlette.requests import Request

from http_mcp._mcp_types.capabilities import ServerCapabilities
from http_mcp._mcp_types.prompts import ProtocolPrompt, RenderedPrompt
from http_mcp._mcp_types.results import CacheScope
from http_mcp.failures import (
    InsufficientScope,
    InvalidArguments,
    PromptInvocationFailed,
    PromptNotFound,
    PromptServerFailure,
    ToolInvocationFailed,
    ToolNotFound,
)

type ToolCallOutcome = (
    BaseModel | ToolNotFound | InsufficientScope | InvalidArguments | ToolInvocationFailed
)
type PromptGetOutcome = (
    RenderedPrompt
    | PromptNotFound
    | InsufficientScope
    | InvalidArguments
    | PromptInvocationFailed
    | PromptServerFailure
)


class ServerInterface(ABC):
    @property
    @abstractmethod
    def version(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def instructions(self) -> str | None:
        raise NotImplementedError

    @property
    @abstractmethod
    def capabilities(self) -> ServerCapabilities:
        raise NotImplementedError

    @property
    @abstractmethod
    def cache_ttl_ms(self) -> int:
        """How long, in milliseconds, a client may treat list results as fresh."""
        raise NotImplementedError

    @property
    @abstractmethod
    def cache_scope(self) -> CacheScope:
        """Whether shared caches may serve list results across authorization contexts."""
        raise NotImplementedError

    @property
    @abstractmethod
    def allowed_origins(self) -> tuple[str, ...]:
        """Origins accepted by the HTTP transport; empty disables the check."""
        raise NotImplementedError

    @property
    @abstractmethod
    def require_origin(self) -> bool:
        """Whether a request with no ``Origin`` header is refused by the allowlist."""
        raise NotImplementedError

    @abstractmethod
    def get_tool_input_schema(self, tool_name: str, request: Request) -> dict | None:
        """Return a tool's input schema, or None when the caller may not see it.

        Answers None both for a tool that does not exist and for one the caller lacks
        the scopes for, so that a caller cannot tell the two apart from the schema
        lookup alone. This runs before dispatch, hence before any authorization check
        the dispatcher applies.
        """
        raise NotImplementedError

    @abstractmethod
    async def call_tool(
        self,
        tool_name: str,
        args: dict,
        request: Request,
    ) -> ToolCallOutcome:
        raise NotImplementedError

    @abstractmethod
    def list_tools(self, request: Request) -> tuple[dict, ...]:
        raise NotImplementedError

    @abstractmethod
    def list_prompts(self, request: Request) -> tuple[ProtocolPrompt, ...]:
        raise NotImplementedError

    @abstractmethod
    async def get_prompt(
        self,
        prompt_name: str,
        arguments: dict,
        request: Request,
    ) -> PromptGetOutcome:
        raise NotImplementedError
