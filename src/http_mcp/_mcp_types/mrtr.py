"""Wire-level MRTR results and continuation parameters."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictStr, field_validator

from http_mcp._json_rcp_types.messages import JSONRPCMessage
from http_mcp._mcp_types.elicitation import ElicitationRequest
from http_mcp._mcp_types.meta import ResultMeta


class ContinuationParams(BaseModel):
    input_responses: dict[str, JsonValue] = Field(
        default_factory=dict,
        serialization_alias="inputResponses",
        validation_alias="inputResponses",
    )
    request_state: StrictStr | None = Field(
        default=None,
        serialization_alias="requestState",
        validation_alias="requestState",
    )

    @field_validator("request_state", mode="before")
    @classmethod
    def _state_is_not_null(cls, value: object) -> object:
        if value is None:
            message = "Request state must be a string when present"
            raise ValueError(message)
        return value


class InputRequiredResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    result_type: Literal["input_required"] = Field(
        default="input_required",
        serialization_alias="resultType",
        validation_alias="resultType",
    )
    meta: ResultMeta = Field(serialization_alias="_meta", validation_alias="_meta")
    input_requests: dict[str, ElicitationRequest] = Field(
        serialization_alias="inputRequests",
        validation_alias="inputRequests",
        min_length=1,
    )
    request_state: str | None = Field(
        default=None,
        serialization_alias="requestState",
        validation_alias="requestState",
    )


class RetryRequiredResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    result_type: Literal["input_required"] = Field(
        default="input_required",
        serialization_alias="resultType",
        validation_alias="resultType",
    )
    meta: ResultMeta = Field(serialization_alias="_meta", validation_alias="_meta")
    request_state: str = Field(serialization_alias="requestState", validation_alias="requestState")


class InputRequiredResponse(JSONRPCMessage):
    result: InputRequiredResult | RetryRequiredResult
