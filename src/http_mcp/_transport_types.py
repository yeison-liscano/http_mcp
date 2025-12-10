from http import HTTPStatus

from pydantic import BaseModel

from http_mcp._json_rcp_types.errors import ErrorCode


class ErrorResponseInfo(BaseModel):
    message_id: int | str | None = None
    protocol_code: ErrorCode
    http_status_code: HTTPStatus
    message: str
    headers: dict[str, str] | None = None
