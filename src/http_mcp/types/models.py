from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel
from starlette.requests import Request

from http_mcp.exceptions import ServerError


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
            raise ServerError(message)

        return cast("TKey", self.request.state.__getattr__(key))


class InvocationResult[TOutput: BaseModel](BaseModel):
    output: TOutput | None
    error_message: str | None

    @classmethod
    def generate_json_schema(cls, output_class: type[TOutput]) -> dict:
        schema = cls.model_json_schema(by_alias=False)
        output_schema = output_class.model_json_schema(by_alias=False)

        schema["$defs"] = {output_class.__name__: output_schema}

        output = [val for val in schema["properties"]["output"]["anyOf"] if "$ref" not in val]

        schema["properties"]["output"]["anyOf"] = [
            {"$ref": f"#/$defs/{output_class.__name__}"},
            *output,
        ]

        return schema
