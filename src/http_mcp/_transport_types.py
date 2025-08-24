from enum import IntEnum
from http import HTTPStatus

from pydantic import BaseModel


class ProtocolErrorCode(IntEnum):
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    METHOD_NOT_FOUND = -32601
    RESOURCE_NOT_FOUND = -32002


class ErrorResponseInfo(BaseModel):
    message_id: int | str | None = None
    protocol_code: ProtocolErrorCode
    http_status_code: HTTPStatus
    message: str
    headers: dict[str, str] | None = None
