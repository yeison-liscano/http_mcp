import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field
from starlette.requests import Request

from http_mcp._json_rcp_types.errors import Error, ErrorCode
from http_mcp.exceptions import ServerError

LOGGER = logging.getLogger(__name__)


class NoArguments(BaseModel):
    pass


@dataclass
class Arguments[TInputs: BaseModel | None]:
    request: Request
    inputs: TInputs

    def get_state_key[TKey](
        self,
        key: str,
        _object_type: type[TKey],
    ) -> TKey:
        if not hasattr(self.request.state, key):
            message = (
                f"Key {key} not found in request state, make sure to add it to the"
                " request state in the lifespan of the application."
            )
            raise ServerError(Error(code=ErrorCode.INTERNAL_ERROR, description=message))

        value = self.request.state.__getattr__(key)
        if not isinstance(value, _object_type):
            LOGGER.error(
                "State key '%s' type mismatch: got %s, expected %s",
                key,
                type(value).__name__,
                _object_type.__name__,
            )
            message = f"State key '{key}' type mismatch: expected type does not match stored type"
            raise ServerError(Error(code=ErrorCode.INTERNAL_ERROR, description=message))

        return value


class ErrorMessage(BaseModel):
    """Returned feedback if the tool invocation was not successful."""

    error_message: str = Field(
        description="The error message if the tool invocation was not successful",
    )
