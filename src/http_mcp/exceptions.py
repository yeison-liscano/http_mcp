"""Exceptions that tool and prompt functions raise to report a failure.

They exist for user code only: `Tool` and `Prompt` catch them at the call boundary and
turn them into the values in `http_mcp.failures`. Nothing else in the library raises them,
apart from `Arguments.get_state_key`, whose failure means the application was wired wrong.
"""

from http_mcp._json_rcp_types.errors import Error, ErrorCode
from http_mcp.failures import prompt_failure_message, tool_failure_message


class BaseError(Exception):
    def __init__(self, error: Error) -> None:
        self.message = error.message
        self.error = error

    def __str__(self) -> str:
        """Return a string representation of the error."""
        return self.message


class ServerError(BaseError):
    """raise error related to server features."""


class ToolInvocationError(ServerError):
    def __init__(self, tool_name: str, message: str) -> None:
        super().__init__(
            Error(
                code=ErrorCode.INTERNAL_ERROR,
                description=tool_failure_message(tool_name, message),
            ),
        )


class PromptInvocationError(ServerError):
    def __init__(self, prompt_name: str, message: str) -> None:
        super().__init__(
            Error(
                code=ErrorCode.INTERNAL_ERROR,
                description=prompt_failure_message(prompt_name, message),
            ),
        )
