import pytest
from pydantic import ValidationError

from http_mcp._mcp_types.tools import ToolsListRequestParams


@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        (None, None),
        (0, 0),
        (1, 1),
        (42, 42),
        ("5", 5),
        ("0", 0),
    ],
    ids=[
        "none",
        "int_zero",
        "int_positive",
        "int_large",
        "str_valid",
        "str_zero",
    ],
)
def test_validate_cursor(input_value: object, expected: int | None) -> None:
    params = ToolsListRequestParams(cursor=input_value)  # type: ignore[arg-type]
    assert params.cursor == expected


@pytest.mark.parametrize(
    "input_value",
    [
        "not_a_number",
        b"10",
        b"not_a_number",
        "",
        3.14,
        [],
        {},
        True,
        -1,
        "-5",
    ],
    ids=[
        "str_invalid",
        "bytes",
        "bytes_invalid",
        "str_empty",
        "float",
        "list",
        "dict",
        "bool",
        "int_negative",
        "str_negative",
    ],
)
def test_validate_cursor_invalid(input_value: object) -> None:
    with pytest.raises(ValidationError, match="Invalid cursor"):
        ToolsListRequestParams(cursor=input_value)  # type: ignore[arg-type]
