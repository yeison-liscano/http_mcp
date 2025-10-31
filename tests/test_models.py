import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, Field

from http_mcp.types import Tool
from http_mcp.types.models import InvocationResult


def test_invocation_result_generate_json_schema() -> None:
    class TestOutput(BaseModel):
        answer: str

    schema = InvocationResult[TestOutput].generate_json_schema(TestOutput)

    class TestOutputSchema(BaseModel):
        output: TestOutput | None
        error_message: str | None

    expected_schema = TestOutputSchema.model_json_schema(by_alias=False)

    for key, value in expected_schema.items():
        if key != "title":
            assert schema[key] == value


class TestOutput(BaseModel):
    answer: str = Field(description="The answer to the question")
    optional_answer: str | None = Field(
        default=None,
        description="The optional answer to the question",
    )
    description: int = Field(description="The description of the answer")
    title: str = Field(default="Test Output", description="The title of the answer")
    items: list[str] = Field(description="The items of the answer")
    optional_items: list[str] | None = Field(
        default=None,
        description="The optional items of the answer",
    )


class TestOutputSchema(BaseModel):
    output: TestOutput | None
    error_message: str | None


def test_complex_invocation_result_generate_json_schema() -> None:
    schema = InvocationResult[TestOutput].generate_json_schema(TestOutput)

    expected_schema = TestOutputSchema.model_json_schema(by_alias=False)

    for key, value in expected_schema.items():
        if key != "title":
            assert schema[key] == value


def test_tool_generate_json_schema() -> None:
    def tool_generate_json_schema_1() -> TestOutput:
        raise NotImplementedError

    def tool_generate_json_schema_2() -> TestOutputSchema:
        raise NotImplementedError

    tool_1 = Tool(
        func=tool_generate_json_schema_1,
        inputs=type(None),
        output=TestOutput,
        return_error_message=True,
    )
    tool_2 = Tool(
        func=tool_generate_json_schema_2,
        inputs=type(None),
        output=TestOutputSchema,
        return_error_message=False,
    )
    schema_1 = tool_1.generate_json_schema()
    schema_2 = tool_2.generate_json_schema()

    test_output = TestOutput(
        answer="test",
        description=1,
        items=["item1", "item2"],
        optional_items=["item3", "item4"],
        optional_answer=None,
        title="Test Output",
    )
    return_value = TestOutputSchema(
        output=test_output,
        error_message=None,
    ).model_dump()

    validator_1 = Draft7Validator(schema_1)
    validator_2 = Draft7Validator(schema_2)

    validator_1.check_schema(return_value)
    validator_2.check_schema(return_value)
    with pytest.raises(SchemaError):
        validator_1.check_schema(test_output.model_dump())
    with pytest.raises(SchemaError):
        validator_2.check_schema(test_output.model_dump())
