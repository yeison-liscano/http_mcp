from pydantic import Field

from http_mcp._json_rcp_types.messages import JSONRPCMessage
from http_mcp._mcp_types.capabilities import ServerCapabilities
from http_mcp._mcp_types.results import CacheableResult


class DiscoverResult(CacheableResult):
    supported_versions: tuple[str, ...] = Field(
        serialization_alias="supportedVersions",
        alias_priority=1,
    )
    capabilities: ServerCapabilities
    instructions: str | None = None


class DiscoverResponse(JSONRPCMessage):
    result: DiscoverResult
