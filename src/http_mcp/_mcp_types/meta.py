"""Per-request and per-result protocol metadata carried in ``_meta``.

Introduced by revision ``2026-07-28``, which removed the ``initialize`` handshake:
every request restates the protocol version and client capabilities so a server
never has to infer them from connection state.
"""

from typing import Any

from pydantic import BaseModel, Field

META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_LOG_LEVEL = "io.modelcontextprotocol/logLevel"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"


class Implementation(BaseModel):
    """Self-reported name and version of a client or server.

    Not verified by the protocol: for display, logging, and debugging only.
    """

    name: str
    version: str
    title: str | None = None


class RequestMeta(BaseModel):
    """The ``io.modelcontextprotocol/*`` fields a modern request must carry."""

    protocol_version: str = Field(validation_alias=META_PROTOCOL_VERSION, alias_priority=1)
    client_capabilities: dict[str, Any] = Field(
        validation_alias=META_CLIENT_CAPABILITIES,
        alias_priority=1,
    )
    client_info: Implementation | None = Field(
        validation_alias=META_CLIENT_INFO,
        alias_priority=1,
        default=None,
    )
    log_level: str | None = Field(
        validation_alias=META_LOG_LEVEL,
        alias_priority=1,
        default=None,
    )


class ResultMeta(BaseModel):
    """The ``_meta`` block servers attach to every modern result."""

    server_info: Implementation = Field(serialization_alias=META_SERVER_INFO, alias_priority=1)
