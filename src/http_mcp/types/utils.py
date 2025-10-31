from pydantic import BaseModel


def generate_union_schema(
    type_a: type[BaseModel],
    type_b: type[BaseModel],
) -> dict:
    """Generate a JSON schema representing the union of two BaseModel types.

    Args:
        type_a: First BaseModel class
        type_b: Second BaseModel class

    Returns:
        A JSON schema with oneOf constraint representing the union of both types

    """
    schema_a = type_a.model_json_schema(by_alias=False)
    schema_b = type_b.model_json_schema(by_alias=False)

    # Merge all definitions from both schemas
    all_defs = {}
    all_defs.update(schema_a.get("$defs", {}))
    all_defs.update(schema_b.get("$defs", {}))

    # Add the main types to definitions if they're not already there
    if type_a.__name__ not in all_defs:
        all_defs[type_a.__name__] = {k: v for k, v in schema_a.items() if k != "$defs"}
    if type_b.__name__ not in all_defs:
        all_defs[type_b.__name__] = {k: v for k, v in schema_b.items() if k != "$defs"}

    return {
        "$defs": all_defs,
        "type": "object",
        "oneOf": [
            {"$ref": f"#/$defs/{type_a.__name__}"},
            {"$ref": f"#/$defs/{type_b.__name__}"},
        ],
    }
