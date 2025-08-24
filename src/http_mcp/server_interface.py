from abc import ABC, abstractmethod

from pydantic import BaseModel
from starlette.requests import Request

from http_mcp.mcp_types.capabilities import ServerCapabilities
from http_mcp.mcp_types.prompts import PromptGetResult, PromptListResult


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
    def capabilities(self) -> ServerCapabilities:
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
    def list_tools(self) -> tuple[dict, ...]:
        raise NotImplementedError

    @abstractmethod
    def list_prompts(self) -> PromptListResult:
        raise NotImplementedError

    @abstractmethod
    async def get_prompt(
        self,
        prompt_name: str,
        arguments: dict,
        request: Request,
    ) -> PromptGetResult:
        raise NotImplementedError
