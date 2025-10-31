from pydantic import BaseModel, Field
from starlette.authentication import has_required_scope

from http_mcp.mcp_types.content import TextContent
from http_mcp.mcp_types.prompts import PromptMessage
from http_mcp.types import Arguments, NoArguments, Prompt
from tests.app.tools import TOOLS


class GetAdvice(BaseModel):
    topic: str = Field(description="The topic to get advice on")
    include_actionable_steps: bool = Field(
        description="Whether to include actionable steps in the advice",
        default=False,
    )


def get_advice(args: Arguments[GetAdvice]) -> tuple[PromptMessage, ...]:
    """Get advice on a topic."""
    template = """
    You are a helpful assistant that can give advice on {topic}.
    """
    if args.inputs.include_actionable_steps:
        template += """
        The advice should include actionable steps.
        """
    return (
        PromptMessage(
            role="user",
            content=TextContent(text=template.format(topic=args.inputs.topic)),
        ),
    )


def get_advice_without_arguments() -> tuple[PromptMessage, ...]:
    """Use this prompt to help the user write test for prompt module."""
    return (
        PromptMessage(
            role="user",
            content=TextContent(
                text="Your objective is to help the user write test for prompt module.",
            ),
        ),
    )


def private_prompt(_args: Arguments[NoArguments]) -> tuple[PromptMessage, ...]:
    """Private prompt that is only accessible to authenticated users."""
    return (
        PromptMessage(
            role="user",
            content=TextContent(text="Hello, world!"),
        ),
    )


def private_multi_scope_prompt(_args: Arguments[NoArguments]) -> tuple[PromptMessage, ...]:
    """Private prompt that is only accessible to authenticated users.

    with the 'private' or 'superuser' scopes.
    """
    return (
        PromptMessage(
            role="user",
            content=TextContent(text="Hello, world!"),
        ),
    )


def execute_all_tools(args: Arguments[NoArguments]) -> tuple[PromptMessage, ...]:
    """Execute all tools."""
    tools = [tool for tool in TOOLS if has_required_scope(args.request, tool.scopes)]
    return (
        PromptMessage(
            role="user",
            content=TextContent(
                text=f"Call the following tools: {', '.join(tool.name for tool in tools)}",
            ),
        ),
    )


PROMPTS = (
    Prompt(
        func=get_advice,
        arguments_type=GetAdvice,
    ),
    Prompt(
        func=get_advice_without_arguments,
        arguments_type=type(None),
    ),
    Prompt(
        func=private_prompt,
        arguments_type=NoArguments,
        scopes=("private",),
    ),
    Prompt(
        func=private_multi_scope_prompt,
        arguments_type=NoArguments,
        scopes=("private", "superuser"),
    ),
    Prompt(
        func=execute_all_tools,
        arguments_type=NoArguments,
    ),
)
