from enum import IntEnum

from pydantic import BaseModel, Field, computed_field


class ErrorCode(IntEnum):
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    METHOD_NOT_FOUND = -32601
    RESOURCE_NOT_FOUND = -32002


class Error(BaseModel):
    code: ErrorCode
    description: str | None = Field(default=None, exclude=True)
    data: dict | None = Field(default=None)

    @computed_field # type: ignore[prop-decorator]
    @property
    def message(self) -> str:
        if self.description:
            return self.description
        return self.code.name.replace("_", " ").title()
