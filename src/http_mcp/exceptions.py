from typing import Literal


class BaseError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message

    def __str__(self) -> str:
        """Return a string representation of the error."""
        return self.message


class ProtocolError(BaseError):
    """raise error related to protocol validations."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Protocol error: {message}")


class ServerError(BaseError):
    """raise error related to server features."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Server error: {message}")


class ToolNotFoundError(ServerError):
    def __init__(self, tool_name: str) -> None:
        super().__init__(f"Tool {tool_name} not found")


class ToolInvocationError(ServerError):
    def __init__(self, tool_name: str, message: str) -> None:
        super().__init__(f"Error calling tool {tool_name}: {message}")


class PromptNotFoundError(ServerError):
    def __init__(self, prompt_name: str) -> None:
        super().__init__(f"Prompt {prompt_name} not found")


class PromptInvocationError(ServerError):
    def __init__(self, prompt_name: str, message: str) -> None:
        super().__init__(f"Error getting prompt {prompt_name}: {message}")


class ArgumentsError(ProtocolError):
    """raise error when the arguments of a tool or prompt are invalid."""

    def __init__(
        self, feature_type: Literal["tool", "prompt"], feature_name: str, message: str,
    ) -> None:
        super().__init__(f"Error validating arguments for {feature_type} {feature_name}: {message}")
