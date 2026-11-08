from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from http_mcp._json_rcp_types.messages import JSONRPCMessage, JSONRPCRequest
from http_mcp._mcp_types.content import TextContent
from http_mcp._mcp_types.pagination import PaginatedRequestParams
from http_mcp._mcp_types.results import CacheableResult, Result


class ToolAnnotations(BaseModel):
    """Developer-supplied hints. Unspecified hints are omitted from the wire."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    title: str | None = None
    read_only_hint: bool | None = Field(default=None, serialization_alias="readOnlyHint")
    destructive_hint: bool | None = Field(default=None, serialization_alias="destructiveHint")
    idempotent_hint: bool | None = Field(default=None, serialization_alias="idempotentHint")
    open_world_hint: bool | None = Field(default=None, serialization_alias="openWorldHint")


class ToolsListResult(CacheableResult):
    tools: tuple[dict, ...]
    next_cursor: str | None = Field(
        serialization_alias="nextCursor",
        default=None,
        alias_priority=1,
    )


class ToolsListResponse(JSONRPCMessage):
    result: ToolsListResult


class ToolsCallSuccess(Result):
    content: tuple[TextContent, ...]
    is_error: Literal[False] = Field(
        serialization_alias="isError",
        alias_priority=1,
        default=False,
    )
    structured_content: JsonValue = Field(
        serialization_alias="structuredContent",
        alias_priority=1,
    )

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        result: dict[str, Any] = handler(self)
        # A root-model null is a result, not an absent optional field. Transports
        # exclude None for optional metadata but must retain this required value.
        key = "structuredContent" if info.by_alias else "structured_content"
        result[key] = self.structured_content
        return result


class ToolsCallFailure(Result):
    content: tuple[TextContent, ...]
    is_error: Literal[True] = Field(
        serialization_alias="isError",
        alias_priority=1,
        default=True,
    )


class ToolsCallStructuredFailure(ToolsCallFailure):
    structured_content: dict[str, str] = Field(serialization_alias="structuredContent")


class ToolsCallResponse(JSONRPCMessage):
    result: ToolsCallSuccess | ToolsCallStructuredFailure | ToolsCallFailure


class ToolsCallRequestParams(BaseModel):
    name: str
    # Optional per the MCP specification: omitted for tools that take no arguments.
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolsCallRequest(JSONRPCRequest):
    method: Literal["tools/call"]
    params: ToolsCallRequestParams


class ToolsListRequestParams(PaginatedRequestParams):
    pass


class ToolsListRequest(JSONRPCRequest):
    method: Literal["tools/list"]
    params: ToolsListRequestParams | None = None
