from typing import Any, Literal

from pydantic import BaseModel, Field

from server.messages import JSONRPCMessage, JSONRPCRequest, TextContent


class ToolsListResult(BaseModel):
    tools: tuple[dict, ...]
    next_cursor: str | None = Field(
        serialization_alias="nextCursor", default=None, alias_priority=1
    )


class ToolsListResponse(JSONRPCMessage):
    result: ToolsListResult


class ToolsCallResult(BaseModel):
    content: tuple[TextContent, ...]
    is_error: bool = Field(serialization_alias="isError", alias_priority=1)
    structured_content: dict[str, Any] | None = Field(
        serialization_alias="structuredContent", default=None, alias_priority=1
    )


class ToolsCallResponse(JSONRPCMessage):
    result: ToolsCallResult


class ToolsCallRequestParams(BaseModel):
    name: str
    arguments: dict[str, Any]


class ToolsCallRequest(JSONRPCRequest):
    method: Literal["tools/call"]
    params: ToolsCallRequestParams


class ToolsListRequestParams(BaseModel):
    cursor: str | None = None


class ToolsListRequest(JSONRPCRequest):
    method: Literal["tools/list"]
    params: ToolsListRequestParams
