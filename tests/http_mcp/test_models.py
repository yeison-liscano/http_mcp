import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel, Field

from http_mcp.types import Tool


class TestOutput(BaseModel):
    status_code: int = Field(description="The status code of the response")
    optional_answer: str | None = Field(
        default=None,
        description="The optional answer to the question",
    )
    description: str = Field(description="The description of the answer")
    title: str = Field(default="Test Output", description="The title of the answer")
    items: list[str] = Field(description="The items of the answer")
    optional_items: list[str] | None = Field(
        default=None,
        description="The optional items of the answer",
    )


def test_invocation_result_generate_union_output_json_schema() -> None:
    def tool_generate_json_schema_1() -> TestOutput:
        raise NotImplementedError

    tool_1 = Tool(
        func=tool_generate_json_schema_1,
        inputs=type(None),
        output=TestOutput,
        return_error_message=True,
    )
    schema_1 = tool_1.generate_json_schema()
    output_schema = schema_1["outputSchema"]

    # Verify the schema itself is valid
    Draft7Validator.check_schema(output_schema)

    # Create validator with the output schema
    validator = Draft7Validator(output_schema)

    # Test that valid TestOutput data validates successfully
    test_output = TestOutput(
        status_code=200,
        description="test",
        items=["item1", "item2"],
        optional_items=["item3", "item4"],
        optional_answer=None,
    )
    validator.validate(test_output.model_dump())

    # Test that valid ErrorMessage data also validates successfully
    error_output = {"error_message": "Something went wrong"}
    validator.validate(error_output)

    with pytest.raises(ValidationError):
        validator.validate({"error_message": 78})
