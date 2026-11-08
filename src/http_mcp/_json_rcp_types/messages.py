from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, StrictInt, StrictStr

from http_mcp._json_rcp_types.errors import Error  # noqa: TC001


class JSONRPCMessage(BaseModel):
    jsonrpc: Literal["2.0"]
    # Errors and notifications have no id. Strict, because lax validation would turn
    # `true` into 1 and `1.0` into 1, answering a request under an id it never sent.
    id: StrictInt | StrictStr | None = None


class JSONRPCRequestEnvelope(JSONRPCMessage):
    """A request envelope, before method selection and parameter validation."""

    id: StrictInt | StrictStr
    method: StrictStr


class JSONRPCNotification(BaseModel):
    jsonrpc: Literal["2.0"]
    method: StrictStr
    params: dict[str, Any] | None = None


class JSONRPCRequest(JSONRPCRequestEnvelope):
    method: Literal[
        "prompts/list",
        "prompts/get",
        "tools/list",
        "tools/call",
        "server/discover",
    ]
    params: dict[str, Any] | BaseModel | None = None


class JSONRPCError(JSONRPCMessage):
    error: Error
