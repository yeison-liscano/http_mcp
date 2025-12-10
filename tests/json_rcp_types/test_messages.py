import pytest
from pydantic import BaseModel, ValidationError

from http_mcp._json_rcp_types.errors import Error, ErrorCode
from http_mcp._json_rcp_types.messages import JSONRPCResponse


def test_jsonrpc_response() -> None:
    class TestResult(BaseModel):
        result: str

    response = JSONRPCResponse(jsonrpc="2.0", id=1, result=TestResult(result="value"))
    assert response.jsonrpc == "2.0"
    assert response.id == 1
    assert response.result == TestResult(result="value")


def test_jsonrpc_response_invalid_error() -> None:
    class TestResult(BaseModel):
        result: str

    with pytest.raises(ValidationError):
        JSONRPCResponse(
            jsonrpc="2.0",
            id=1,
            result=TestResult(result="value"),
            error=Error(code=ErrorCode.INVALID_PARAMS, description="Invalid parameters"),
        )
