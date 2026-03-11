from typing import Literal

from http_mcp._json_rcp_types.errors import Error, ErrorCode

_MAX_NAME_LENGTH = 100


def _safe_name(name: str) -> str:
    """Truncate a user-supplied name for safe inclusion in error messages."""
    return name[:_MAX_NAME_LENGTH]


class BaseError(Exception):
    def __init__(self, error: Error) -> None:
        self.message = error.message
        self.error = error

    def __str__(self) -> str:
        """Return a string representation of the error."""
        return self.message


class ProtocolError(BaseError):
    """raise error related to protocol validations."""


class ServerError(BaseError):
    """raise error related to server features."""


class ToolNotFoundError(ServerError):
    def __init__(self, tool_name: str) -> None:
        super().__init__(
            Error(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                description=f"Tool {_safe_name(tool_name)} not found",
            ),
        )


class ToolInvocationError(ServerError):
    def __init__(self, tool_name: str, message: str) -> None:
        super().__init__(
            Error(
                code=ErrorCode.INTERNAL_ERROR,
                description=f"Error calling tool {_safe_name(tool_name)}: {message}",
            ),
        )


class PromptNotFoundError(ServerError):
    def __init__(self, prompt_name: str) -> None:
        super().__init__(
            Error(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                description=f"Prompt {_safe_name(prompt_name)} not found",
            ),
        )


class PromptInvocationError(ServerError):
    def __init__(self, prompt_name: str, message: str) -> None:
        super().__init__(
            Error(
                code=ErrorCode.INTERNAL_ERROR,
                description=f"Error getting prompt {_safe_name(prompt_name)}: {message}",
            ),
        )


class ArgumentsError(ProtocolError):
    """raise error when the arguments of a tool or prompt are invalid."""

    def __init__(
        self,
        feature_type: Literal["tool", "prompt"],
        feature_name: str,
        message: str,
    ) -> None:
        description = (
            f"Error validating arguments for {feature_type} {_safe_name(feature_name)}: {message}"
        )
        super().__init__(Error(code=ErrorCode.INVALID_PARAMS, description=description))
