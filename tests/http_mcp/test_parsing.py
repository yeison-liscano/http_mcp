import json

import pytest
from pydantic import BaseModel

from http_mcp._parsing import InvalidJson, InvalidModel, Parsed, parse_json, parse_model


class Sample(BaseModel):
    count: int


def test_parse_json_returns_the_decoded_document() -> None:
    assert parse_json(b'{"a": 1}') == Parsed({"a": 1})


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"{", id="malformed"),
        pytest.param(b"", id="empty"),
        pytest.param(b"\xff\xfe{", id="not-utf-8"),
        pytest.param(b"[" * 200_000, id="nested-past-the-recursion-limit"),
        pytest.param(b"1" * 5_000, id="integer-past-the-digit-limit"),
    ],
)
def test_parse_json_reports_invalid_documents_as_a_value(data: bytes) -> None:
    assert parse_json(data) == InvalidJson()


def test_parse_model_returns_the_validated_model() -> None:
    assert parse_model(Sample, {"count": 1}) == Parsed(Sample(count=1))


def test_parse_model_reports_rejected_input_without_echoing_it() -> None:
    match parse_model(Sample, {"count": "secret-value"}):
        case InvalidModel(description=description):
            assert [error["field"] for error in json.loads(description)] == ["count"]
            assert "secret-value" not in description
        case Parsed():
            pytest.fail("the input should have been rejected")
