from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel
from starlette.requests import Request

from http_mcp.exceptions import ServerError


@dataclass
class Arguments[TInputs: BaseModel]:
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
            raise ServerError(message)

        return cast("TKey", self.request.state.__getattr__(key))
