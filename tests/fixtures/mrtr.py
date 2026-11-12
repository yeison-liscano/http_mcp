"""An application using only public MRTR APIs, also runnable as a STDIO server."""

import asyncio
from typing import assert_never

from pydantic import BaseModel, ConfigDict

from http_mcp.server import MCPServer
from http_mcp.types import (
    Arguments,
    CancelledElicitation,
    DeclinedElicitation,
    ElicitationRequest,
    ElicitationSchema,
    FormElicitation,
    InputRequired,
    InvalidContinuationState,
    InvalidInputResponse,
    InvocationContext,
    InvocationResult,
    MissingInputResponse,
    NoArguments,
    Prompt,
    PromptMessage,
    RetryRequired,
    SignedStateCodec,
    StringField,
    TextContent,
    Tool,
    ValidatedInput,
    VerifiedState,
)

CODEC = SignedStateCodec(b"unit-test-only-signing-key-32-bytes")


class Profile(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    nickname: str


class Greeting(BaseModel):
    message: str


def _request_profile(state: str) -> InputRequired:
    return InputRequired(
        input_requests={
            "profile": ElicitationRequest(
                params=FormElicitation(
                    message="What should we call you?",
                    requested_schema=ElicitationSchema(
                        properties={"nickname": StringField()},
                        required=("nickname",),
                    ),
                ),
            ),
        },
        request_state=state,
    )


def greeting(args: Arguments[NoArguments]) -> InvocationResult[Greeting]:
    context = args.continuation
    if context is None:
        return InvalidContinuationState()
    # This fixture is a trusted local application. Remote applications must bind to
    # their authenticated principal, never a client-provided identity header.
    binding = context.bind("trusted-local-fixture", client_id="trusted-local-client")
    state = context.request_state
    if state is None:
        return _request_profile(CODEC.seal({"operation": "greeting"}, binding))
    match CODEC.open(state, binding):
        case InvalidContinuationState() as failure:
            return failure
        case VerifiedState():
            pass
        case _ as unreachable:
            assert_never(unreachable)
    return _complete_greeting(context, state)


def _complete_greeting(context: InvocationContext, state: str) -> InvocationResult[Greeting]:
    match context.form_content("profile", Profile):
        case ValidatedInput(value=profile):
            return Greeting(message=f"Hello, {profile.nickname}")
        case MissingInputResponse():
            return _request_profile(state)
        case InvalidInputResponse() as failure:
            return failure
        case DeclinedElicitation():
            return Greeting(message="Declined")
        case CancelledElicitation():
            return Greeting(message="Cancelled")
        case _ as unreachable:
            assert_never(unreachable)


async def greeting_prompt(
    args: Arguments[NoArguments],
) -> InvocationResult[tuple[PromptMessage, ...]]:
    match greeting(args):
        case Greeting(message=message):
            return (PromptMessage(role="assistant", content=TextContent(text=message)),)
        case (
            InputRequired()
            | RetryRequired()
            | InvalidContinuationState()
            | InvalidInputResponse() as outcome
        ):
            return outcome
        case _ as unreachable:
            assert_never(unreachable)


def create_server() -> MCPServer:
    return MCPServer(
        name="mrtr-test",
        version="1.0.0",
        tools=(Tool(func=greeting, inputs=NoArguments, output=Greeting),),
        prompts=(Prompt(func=greeting_prompt, arguments_type=NoArguments),),
    )


def run_stdio() -> None:
    asyncio.run(create_server().serve_stdio())
