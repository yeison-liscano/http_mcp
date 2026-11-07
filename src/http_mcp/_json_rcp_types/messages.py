from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

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
        "server/discover",
    ]
    params: dict[str, Any] | BaseModel | None = None


class JSONRPCError(JSONRPCMessage):
    error: Error
