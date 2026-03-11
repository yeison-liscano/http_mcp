from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from http_mcp._json_rcp_types.messages import JSONRPCMessage, JSONRPCRequest
from http_mcp._mcp_types.content import TextContent


class ToolsListResult(BaseModel):
    tools: tuple[dict, ...]
    next_cursor: str | None = Field(
        serialization_alias="nextCursor",
        default=None,
        alias_priority=1,
    )


class ToolsListResponse(JSONRPCMessage):
    result: ToolsListResult


class ToolsCallResult(BaseModel):
    content: tuple[TextContent, ...]
    is_error: bool = Field(serialization_alias="isError", alias_priority=1)
    structured_content: dict[str, Any] | None = Field(
        serialization_alias="structuredContent",
        default=None,
        alias_priority=1,
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
    cursor: int | None = None

    @field_validator("cursor", mode="before")
    @classmethod
    def validate_cursor(cls, v: object) -> int | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, int | str | bytes):
            try:
                return int(v)
            except (ValueError, TypeError):
                return None
        return None


class ToolsListRequest(JSONRPCRequest):
    method: Literal["tools/list"]
    params: ToolsListRequestParams | None = None
