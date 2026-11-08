from pydantic import BaseModel, field_validator


class PaginatedRequestParams(BaseModel):
    """Decode this server's string cursors into nonnegative offsets."""

    cursor: int | None = None

    @field_validator("cursor", mode="before")
    @classmethod
    def _decode_cursor(cls, value: object) -> int | None:
        if value is None:
            return None
        message = "Invalid cursor"
        if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
            raise ValueError(message)
        try:
            return int(value)
        except ValueError as error:
            raise ValueError(message) from error
