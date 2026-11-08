from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from http_mcp._json_rcp_types.messages import JSONRPCMessage, JSONRPCRequest
from http_mcp._mcp_types.content import TextContent
from http_mcp._mcp_types.pagination import PaginatedRequestParams
from http_mcp._mcp_types.results import CacheableResult, Result


class PromptGetRequestParams(BaseModel):
    name: str
    # Optional per the MCP specification: omitted for prompts that take no arguments.
    arguments: dict = Field(default_factory=dict)


class PromptGetRequest(JSONRPCRequest):
    method: Literal["prompts/get"]
    params: PromptGetRequestParams


class PromptListRequestParams(PaginatedRequestParams):
    pass


class PromptListRequest(JSONRPCRequest):
    method: Literal["prompts/list"]
    params: PromptListRequestParams | None = None


class PromptArgument(BaseModel):
    name: str = Field(description="The name of the argument")
    description: str
    required: bool


class ProtocolPrompt(BaseModel):
    name: str
    title: str
    description: str
    arguments: tuple[PromptArgument, ...]


class PromptListResult(CacheableResult):
    prompts: tuple[ProtocolPrompt, ...]
    next_cursor: str | None = Field(
        serialization_alias="nextCursor",
        alias_priority=1,
        default=None,
    )


class PromptsListResponse(JSONRPCMessage):
    result: PromptListResult


class PromptMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: TextContent


@dataclass(frozen=True)
class RenderedPrompt:
    """What a prompt function produced, before the transport wraps it in a result."""

    description: str
    messages: tuple[PromptMessage, ...]
    type: Literal["rendered_prompt"] = "rendered_prompt"


class PromptGetResult(Result):
    description: str
    messages: tuple[PromptMessage, ...]


class PromptsGetResponse(JSONRPCMessage):
    result: PromptGetResult
