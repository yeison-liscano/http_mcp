from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ValidationInfo, field_validator

from http_mcp._json_rcp_types.errors import Error  # noqa: TC001


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
    def validate_error(cls, value: Error | None, info: ValidationInfo) -> Error | None:
        result = info.data.get("result")
        if value is not None and result is not None:
            message = "result and error cannot be set at the same time"
            raise ValueError(message)
        if value is None and result is None:
            message = "either result or error must be set"
            raise ValueError(message)
        return value


class JSONRPCNotification(BaseModel):
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/initialized", "notifications/unsubscribe"]
    params: dict[str, Any] | BaseModel | None = None


class JSONRPCError(JSONRPCMessage):
    error: Error
