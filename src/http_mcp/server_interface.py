from abc import ABC, abstractmethod
from typing import Generic

from pydantic import BaseModel
from starlette.requests import Request

from http_mcp.mcp_types.capabilities import ServerCapabilities
from http_mcp.mcp_types.prompts import PromptGetResult, PromptListResult
from http_mcp.tools import TToolsContext


class ServerInterface(ABC, Generic[TToolsContext]):
    @property
    @abstractmethod
    def context(self) -> TToolsContext | None:
        raise NotImplementedError

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
        context: TToolsContext,
    ) -> BaseModel:
        raise NotImplementedError

    @abstractmethod
    def list_tools(self) -> tuple[dict, ...]:
        raise NotImplementedError

    @abstractmethod
    def list_prompts(self) -> PromptListResult:
        raise NotImplementedError

    @abstractmethod
    async def get_prompt(self, prompt_name: str, arguments: dict) -> PromptGetResult:
        raise NotImplementedError
