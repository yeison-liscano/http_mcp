"""Unit tests for the `Mcp-Name` / `Mcp-Param-*` header helpers (revision 2026-07-28)."""

from base64 import b64encode

import pytest

from http_mcp._mcp_types.headers import (
    MISSING,
    collect_header_params,
    decode_header_value,
    extract_argument,
    is_valid_header_value,
    values_match,
)


def sentinel(value: str) -> str:
    return f"=?base64?{b64encode(value.encode('utf-8')).decode('ascii')}?="


# ---------------------------------------------------------------------------
# decode_header_value
# ---------------------------------------------------------------------------


def test_plain_values_pass_through_unchanged() -> None:
    assert decode_header_value("us-west1") == "us-west1"


@pytest.mark.parametrize("value", ["Hello, 世界", " padded ", "line1\nline2", "=?base64?literal?="])
def test_sentinel_round_trips(value: str) -> None:
    assert decode_header_value(sentinel(value)) == value


@pytest.mark.parametrize(
    "value",
    ["=?base64?not!valid!?=", f"=?base64?{b64encode(bytes([255])).decode()}?="],
)
def test_malformed_sentinel_payloads_are_rejected(value: str) -> None:
    assert decode_header_value(value) is None


def test_a_value_too_short_to_hold_both_markers_is_not_a_sentinel() -> None:
    """`=?base64?=` overlaps its own prefix and suffix; it is a literal, not an envelope."""
    assert decode_header_value("=?base64?=") == "=?base64?="


# ---------------------------------------------------------------------------
# is_valid_header_value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["us-west1", "a b", "\ttabbed", "", "~"])
def test_visible_ascii_space_and_tab_are_valid(value: str) -> None:
    assert is_valid_header_value(value)


@pytest.mark.parametrize("value", ["line1\nline2", "carriage\rreturn", "世界", "\x00"])
def test_control_characters_and_non_ascii_are_invalid(value: str) -> None:
    assert not is_valid_header_value(value)


# ---------------------------------------------------------------------------
# collect_header_params
# ---------------------------------------------------------------------------


def test_top_level_and_nested_properties_are_collected() -> None:
    schema = {
        "type": "object",
        "properties": {
            "region": {"type": "string", "x-mcp-header": "Region"},
            "nested": {
                "type": "object",
                "properties": {"tenant": {"type": "string", "x-mcp-header": "Tenant"}},
            },
        },
    }

    assert collect_header_params(schema) == {
        "region": ("region",),
        "tenant": ("nested", "tenant"),
    }


def test_header_names_are_keyed_case_insensitively() -> None:
    schema = {"properties": {"region": {"x-mcp-header": "ReGiOn"}}}

    assert collect_header_params(schema) == {"region": ("region",)}


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param(
            {"properties": {"rows": {"type": "array", "items": {"x-mcp-header": "Row"}}}},
            id="through-items",
        ),
        pytest.param(
            {"properties": {"choice": {"anyOf": [{"x-mcp-header": "Choice"}]}}},
            id="through-anyOf",
        ),
        pytest.param(
            {
                "$defs": {"Nested": {"properties": {"tenant": {"x-mcp-header": "Tenant"}}}},
                "properties": {"nested": {"$ref": "#/$defs/Nested"}},
            },
            id="through-ref",
        ),
        pytest.param(
            {"properties": {"maybe": {"if": {"x-mcp-header": "Maybe"}}}},
            id="through-conditional",
        ),
    ],
)
def test_annotations_that_are_not_statically_reachable_are_ignored(schema: dict) -> None:
    assert collect_header_params(schema) == {}


@pytest.mark.parametrize(
    "schema",
    [
        {},
        {"properties": "not-an-object"},
        {"properties": {"region": "not-a-schema"}},
        {"properties": {"region": {"x-mcp-header": ""}}},
        {"properties": {"region": {"x-mcp-header": 42}}},
    ],
)
def test_absent_or_unusable_annotations_yield_nothing(schema: dict) -> None:
    assert collect_header_params(schema) == {}


# ---------------------------------------------------------------------------
# extract_argument
# ---------------------------------------------------------------------------


def test_a_value_is_read_from_its_exact_path() -> None:
    assert extract_argument({"nested": {"tenant": "acme"}}, ("nested", "tenant")) == "acme"


def test_an_explicit_null_is_distinguished_from_an_absent_key() -> None:
    assert extract_argument({"region": None}, ("region",)) is None
    assert extract_argument({}, ("region",)) is MISSING


def test_a_path_running_through_a_non_mapping_is_missing() -> None:
    assert extract_argument({"nested": "scalar"}, ("nested", "tenant")) is MISSING


def test_the_missing_sentinel_is_readable() -> None:
    assert repr(MISSING) == "<missing>"


# ---------------------------------------------------------------------------
# values_match
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header_value", "body_value", "expected"),
    [
        ("true", True, True),
        ("false", False, True),
        ("True", True, False),
        ("1", True, False),
        ("42", 42, True),
        ("42.0", 42, True),
        ("42", 41, False),
        ("not-a-number", 42, False),
        ("us-west1", "us-west1", True),
        ("us-west1", "eu-west1", False),
        ("anything", ["a", "list"], False),
    ],
)
def test_values_are_compared_by_type(
    header_value: str,
    body_value: object,
    *,
    expected: bool,
) -> None:
    assert values_match(header_value, body_value) is expected
