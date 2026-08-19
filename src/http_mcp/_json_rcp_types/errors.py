from enum import IntEnum

from pydantic import BaseModel, Field, computed_field


class ErrorCode(IntEnum):
    """JSON-RPC and MCP error codes.

    ``-32020`` upwards is the sub-range revision ``2026-07-28`` reserved for the MCP
    specification. ``-32002`` (resource not found) was retired by that revision and
    must not be emitted: unknown tools and prompts report ``INVALID_PARAMS``, which
    is what the tools and prompts specs have always prescribed.
    """

    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    HEADER_MISMATCH = -32020
    MISSING_REQUIRED_CLIENT_CAPABILITY = -32021
    UNSUPPORTED_PROTOCOL_VERSION = -32022


class Error(BaseModel):
    code: ErrorCode
    description: str | None = Field(default=None, exclude=True)
    data: dict | None = Field(default=None)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message(self) -> str:
        if self.description:
            return self.description
        return self.code.name.replace("_", " ").title()
