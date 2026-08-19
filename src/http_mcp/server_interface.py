from abc import ABC, abstractmethod

from pydantic import BaseModel
from starlette.requests import Request

from http_mcp._mcp_types.capabilities import ServerCapabilities
from http_mcp._mcp_types.prompts import PromptGetResult, PromptListResult
from http_mcp._mcp_types.results import CacheScope


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

    @abstractmethod
    def get_tool_input_schema(self, tool_name: str) -> dict | None:
        """Return a tool's input schema, or None when no such tool exists."""
        raise NotImplementedError

    @abstractmethod
    async def call_tool(
        self,
        tool_name: str,
        args: dict,
        request: Request,
    ) -> BaseModel:
        raise NotImplementedError

    @abstractmethod
    def list_tools(self, request: Request) -> tuple[dict, ...]:
        raise NotImplementedError

    @abstractmethod
    def list_prompts(self, request: Request) -> PromptListResult:
        raise NotImplementedError

    @abstractmethod
    async def get_prompt(
        self,
        prompt_name: str,
        arguments: dict,
        request: Request,
    ) -> PromptGetResult:
        raise NotImplementedError
