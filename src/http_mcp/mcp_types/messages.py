from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from http_mcp.mcp_types.capabilities import ServerCapabilities  # noqa: TC001


class JSONRPCMessage(BaseModel):
    jsonrpc: Literal["2.0"]
    id: int | str | None = None  # Errors and notifications has no id


class JSONRPCRequest(JSONRPCMessage):
    method: Literal[
        "prompts/list",
        "prompts/get",
        "tools/list",
        "tools/call",
        "initialize",
        "notifications/subscribe",
        "notifications/unsubscribe",
        "notifications/initialized",
    ]
    params: dict[str, Any] | BaseModel | None = None


class JSONRPCResponse(JSONRPCMessage):
    result: BaseModel | None = None
    error: Error | None = None

    @field_validator("error")
    @classmethod
    def validate_error(cls, v: Error | None) -> Error | None:
        if cls.result is not None:
            message = "result and error cannot be set at the same time"
            raise ValueError(message)
        return v


class JSONRPCNotification(BaseModel):
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/initialized", "notifications/unsubscribe"]
    params: dict[str, Any] | BaseModel | None = None


class Error(BaseModel):
    code: int
    message: str
    data: dict[str, Any] | None = None


class JSONRPCError(JSONRPCMessage):
    error: Error


class InitializationRequest(JSONRPCRequest):
    method: Literal["initialize"]
    params: InitializationRequestParams


class InitializationRequestParams(BaseModel):
    protocol_version: str = Field(validation_alias="protocolVersion", alias_priority=1)
    client_info: dict[str, Any] = Field(validation_alias="clientInfo", alias_priority=1)
    capabilities: dict[str, Any] = Field(validation_alias="capabilities", alias_priority=1)


class ServerInfo(BaseModel):
    name: str
    version: str


class InitializeResponseResult(BaseModel):
    protocol_version: str = Field(serialization_alias="protocolVersion", alias_priority=1)
    server_info: ServerInfo = Field(serialization_alias="serverInfo", alias_priority=1)
    capabilities: ServerCapabilities = Field(serialization_alias="capabilities", alias_priority=1)
    instructions: str | None = None


class InitializeResponse(JSONRPCMessage):
    result: InitializeResponseResult
