from typing import Any

from pydantic import BaseModel, Field


class Capability(BaseModel):
    list_changed: bool = Field(serialization_alias="listChanged", alias_priority=1)


class ServerCapabilities(BaseModel):
    prompts: Capability | None = None
    tools: Capability | None = None
    # Opt-in support for features outside the core protocol, keyed by extension id.
    extensions: dict[str, dict[str, Any]] | None = None
