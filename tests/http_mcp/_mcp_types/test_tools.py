import pytest

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
        (b"10", 10),
        (b"0", 0),
        ("not_a_number", None),
        (b"not_a_number", None),
        ("", None),
        (3.14, None),
        ([], None),
        ({}, None),
        (True, None),
    ],
    ids=[
        "none",
        "int_zero",
        "int_positive",
        "int_large",
        "str_valid",
        "str_zero",
        "bytes_valid",
        "bytes_zero",
        "str_invalid",
        "bytes_invalid",
        "str_empty",
        "float",
        "list",
        "dict",
        "bool",
    ],
)
def test_validate_cursor(input_value: object, expected: int | None) -> None:
    params = ToolsListRequestParams(cursor=input_value)  # type: ignore[arg-type]
    assert params.cursor == expected
