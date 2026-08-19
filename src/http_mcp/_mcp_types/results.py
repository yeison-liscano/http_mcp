"""Base result shapes shared by every MCP method.

Revision ``2026-07-28`` added ``resultType`` to all results, a ``_meta`` block
identifying the server, and caching hints on list-style results. Legacy revisions
define none of them, so the fields default to ``None`` and are dropped by the
``exclude_none=True`` serialization the transports use. Only the modern dispatch
path fills them in.
"""

from typing import Literal

from pydantic import BaseModel, Field

from http_mcp._mcp_types.meta import ResultMeta

ResultType = Literal["complete"]
CacheScope = Literal["public", "private"]


class Result(BaseModel):
    result_type: ResultType | None = Field(
        serialization_alias="resultType",
        alias_priority=1,
        default=None,
    )
    meta: ResultMeta | None = Field(
        serialization_alias="_meta",
        alias_priority=1,
        default=None,
    )


class CacheableResult(Result):
    """A result the client may cache, per the caching utility.

    Carried by ``server/discover``, ``tools/list``, and ``prompts/list``.
    """

    ttl_ms: int | None = Field(serialization_alias="ttlMs", alias_priority=1, default=None)
    cache_scope: CacheScope | None = Field(
        serialization_alias="cacheScope",
        alias_priority=1,
        default=None,
    )
