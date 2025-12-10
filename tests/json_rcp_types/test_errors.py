from http_mcp._json_rcp_types.errors import Error, ErrorCode


def test_error_message() -> None:
    error = Error(code=ErrorCode.INVALID_PARAMS, description="Invalid parameters")
    assert error.message == "Invalid parameters"

    error = Error(code=ErrorCode.INVALID_PARAMS)
    assert error.message == "Invalid Params"

    error = Error(code=ErrorCode.INVALID_PARAMS, data={"foo": "bar"})
    assert error.message == "Invalid Params"
