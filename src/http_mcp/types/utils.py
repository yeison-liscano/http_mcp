from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, TypeAdapter

if TYPE_CHECKING:
    from typing_extensions import TypeForm


def generate_union_schema(
    type_a: type[BaseModel],
    type_b: type[BaseModel],
) -> dict:
    """Generate a JSON schema representing the union of two BaseModel types.

    Args:
        type_a: First BaseModel class
        type_b: Second BaseModel class

    Returns:
        A serialization schema representing either model on the wire.

    """
    # The union is a runtime type expression built from the supplied model classes.
    schema_type = cast("TypeForm[BaseModel]", type_a | type_b)
    return TypeAdapter(schema_type).json_schema(by_alias=True, mode="serialization")
