from abc import ABC, abstractmethod
from typing import Generic

from pydantic import BaseModel
from starlette.requests import Request

from server.models import ServerCapabilities, TToolsContext


class ServerInterface(ABC, Generic[TToolsContext]):
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
    async def list_tools(self) -> tuple[dict, ...]:
        raise NotImplementedError

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
