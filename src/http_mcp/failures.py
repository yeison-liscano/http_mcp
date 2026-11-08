"""Expected failures of tools and prompts, expressed as values.

An unknown tool, a rejected argument, or a denied scope is an ordinary outcome of
serving a request, so it travels through return types and every caller has to handle
it. Exceptions are kept for crashes.
"""

from dataclasses import dataclass
from typing import Literal

from http_mcp._json_rcp_types.errors import ErrorCode

_MAX_NAME_LENGTH = 100


def safe_name(name: str) -> str:
    """Truncate a user-supplied name for safe inclusion in error messages."""
    return name[:_MAX_NAME_LENGTH]


def tool_failure_message(tool_name: str, detail: str) -> str:
    return f"Error calling tool {safe_name(tool_name)}: {detail}"


def prompt_failure_message(prompt_name: str, detail: str) -> str:
    return f"Error getting prompt {safe_name(prompt_name)}: {detail}"


@dataclass(frozen=True)
class ToolNotFound:
    name: str
    type: Literal["tool_not_found"] = "tool_not_found"

    @property
    def message(self) -> str:
        return f"Tool {safe_name(self.name)} not found"


@dataclass(frozen=True)
class PromptNotFound:
    name: str
    type: Literal["prompt_not_found"] = "prompt_not_found"

    @property
    def message(self) -> str:
        return f"Prompt {safe_name(self.name)} not found"


@dataclass(frozen=True)
class InsufficientScope:
    """The request has a valid token but lacks the scopes a tool or prompt requires.

    The HTTP transport answers 403 Forbidden to trigger the OAuth 2.1 step-up
    authorization flow. The STDIO transport answers with a JSON-RPC error.
    """

    required_scopes: tuple[str, ...]
    type: Literal["insufficient_scope"] = "insufficient_scope"


@dataclass(frozen=True)
class InvalidArguments:
    """The arguments of a tool or prompt do not satisfy its input model."""

    feature_type: Literal["tool", "prompt"]
    name: str
    details: str
    type: Literal["invalid_arguments"] = "invalid_arguments"

    @property
    def message(self) -> str:
        return (
            f"Error validating arguments for {self.feature_type} "
            f"{safe_name(self.name)}: {self.details}"
        )


@dataclass(frozen=True)
class ToolInvocationFailed:
    """A tool function failed. Reported to the client as a result with `isError` set."""

    message: str
    type: Literal["tool_invocation_failed"] = "tool_invocation_failed"


@dataclass(frozen=True)
class PromptInvocationFailed:
    """A prompt function failed. Reported as a result with the message as description."""

    message: str
    type: Literal["prompt_invocation_failed"] = "prompt_invocation_failed"


@dataclass(frozen=True)
class PromptServerFailure:
    """A prompt function raised `ServerError`. Reported as a JSON-RPC error."""

    code: ErrorCode
    message: str
    type: Literal["prompt_server_failure"] = "prompt_server_failure"
