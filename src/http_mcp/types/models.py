import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field
from starlette.requests import Request

from http_mcp._json_rcp_types.errors import Error, ErrorCode
from http_mcp.exceptions import ServerError
from http_mcp.types.continuation import INVOCATION_CONTEXT_KEY, InvocationContext

LOGGER = logging.getLogger(__name__)
_WIRING_ERROR = "Internal server error"


class NoArguments(BaseModel):
    pass


@dataclass
class Arguments[TInputs: BaseModel | None]:
    request: Request
    inputs: TInputs

    @property
    def continuation(self) -> InvocationContext | None:
        """MRTR context when invoked over a transport; absent on direct calls."""
        context = self.request.scope.get(INVOCATION_CONTEXT_KEY)
        return context if isinstance(context, InvocationContext) else None

    def get_state_key[TKey](
        self,
        key: str,
        _object_type: type[TKey],
    ) -> TKey:
        # Both failures mean the application was wired wrong. The detail goes to the log
        # for the developer; the client only learns that the server failed.
        if not hasattr(self.request.state, key):
            LOGGER.error(
                "Key '%s' not found in request state, make sure to add it to the"
                " request state in the lifespan of the application.",
                key,
            )
            raise ServerError(Error(code=ErrorCode.INTERNAL_ERROR, description=_WIRING_ERROR))

        value = self.request.state.__getattr__(key)
        if not isinstance(value, _object_type):
            LOGGER.error(
                "State key '%s' type mismatch: got %s, expected %s",
                key,
                type(value).__name__,
                _object_type.__name__,
            )
            raise ServerError(Error(code=ErrorCode.INTERNAL_ERROR, description=_WIRING_ERROR))

        return value


class ErrorMessage(BaseModel):
    """Returned feedback if the tool invocation was not successful."""

    error_message: str = Field(
        description="The error message if the tool invocation was not successful",
    )
