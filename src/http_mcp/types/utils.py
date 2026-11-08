from pydantic import BaseModel, TypeAdapter


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
    return TypeAdapter(type_a | type_b).json_schema(by_alias=True, mode="serialization")
