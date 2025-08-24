from pydantic import BaseModel, Field

from http_mcp.mcp_types.content import TextContent
from http_mcp.mcp_types.prompts import PromptMessage
from http_mcp.types import Arguments, Prompt


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


PROMPTS = (
    Prompt(
        func=get_advice,
        arguments_type=GetAdvice,
    ),
)
