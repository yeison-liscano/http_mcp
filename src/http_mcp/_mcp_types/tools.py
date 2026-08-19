from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from http_mcp._json_rcp_types.messages import JSONRPCMessage, JSONRPCRequest
from http_mcp._mcp_types.content import TextContent
from http_mcp._mcp_types.results import CacheableResult, Result


class ToolsListResult(CacheableResult):
    tools: tuple[dict, ...]
    next_cursor: str | None = Field(
        serialization_alias="nextCursor",
        default=None,
        alias_priority=1,
    )


class ToolsListResponse(JSONRPCMessage):
    result: ToolsListResult


class ToolsCallResult(Result):
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
    # Optional per the MCP specification: omitted for tools that take no arguments.
    arguments: dict[str, Any] = Field(default_factory=dict)


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
        invalid_cursor_msg = "Invalid cursor"
        if isinstance(v, bool) or not isinstance(v, int | str):
            # ValueError (not TypeError) so pydantic reports it as a validation error
            raise ValueError(invalid_cursor_msg)  # noqa: TRY004
        try:
            cursor = int(v)
        except ValueError as e:
            raise ValueError(invalid_cursor_msg) from e
        if cursor < 0:
            raise ValueError(invalid_cursor_msg)
        return cursor


class ToolsListRequest(JSONRPCRequest):
    method: Literal["tools/list"]
    params: ToolsListRequestParams | None = None
