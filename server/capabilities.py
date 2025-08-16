from pydantic import BaseModel, Field


class Capability(BaseModel):
    list_changed: bool = Field(serialization_alias="listChanged", alias_priority=1)
    subscribe: bool = Field(serialization_alias="subscribe", alias_priority=1)


class ServerCapabilities(BaseModel):
    prompts: Capability | None = None
    tools: Capability | None = None
