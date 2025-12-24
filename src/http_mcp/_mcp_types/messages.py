from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from http_mcp._json_rcp_types.messages import JSONRPCMessage, JSONRPCRequest
from http_mcp._mcp_types.capabilities import ServerCapabilities  # noqa: TC001


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
