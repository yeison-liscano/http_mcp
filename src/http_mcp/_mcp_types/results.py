"""Base result shapes shared by every MCP method.

Revision ``2026-07-28`` requires ``resultType`` and a ``_meta`` block identifying the
server on all results, and caching hints on list-style results. The fields are required
here so that a result missing them cannot be built.
"""

from typing import Literal

from pydantic import BaseModel, Field

from http_mcp._mcp_types.meta import ResultMeta

ResultType = Literal["complete"]
CacheScope = Literal["public", "private"]


class Result(BaseModel):
    result_type: ResultType = Field(
        serialization_alias="resultType",
        alias_priority=1,
        default="complete",
    )
    meta: ResultMeta = Field(serialization_alias="_meta", alias_priority=1)


class CacheableResult(Result):
    """A result the client may cache, per the caching utility.

    Carried by ``server/discover``, ``tools/list``, and ``prompts/list``.
    """

    ttl_ms: int = Field(serialization_alias="ttlMs", alias_priority=1)
    cache_scope: CacheScope = Field(serialization_alias="cacheScope", alias_priority=1)
