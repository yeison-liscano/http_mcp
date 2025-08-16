class ToolError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message

    def __str__(self) -> str:
        """Return a string representation of the error."""
        return self.message


class ToolNotFoundError(ToolError):
    def __init__(self, tool_name: str) -> None:
        super().__init__(f"Tool {tool_name} not found")


class ToolInvocationError(ToolError):
    def __init__(self, tool_name: str, error: Exception) -> None:
        super().__init__(f"Error calling tool {tool_name}: {error}")


class PromptError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message

    def __str__(self) -> str:
        """Return a string representation of the error."""
        return self.message


class PromptNotFoundError(PromptError):
    def __init__(self, prompt_name: str) -> None:
        super().__init__(f"Prompt {prompt_name} not found")


class PromptInvocationError(PromptError):
    def __init__(self, prompt_name: str, error: Exception) -> None:
        super().__init__(f"Error getting prompt {prompt_name}: {error}")
