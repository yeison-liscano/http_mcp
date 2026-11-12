# Multi Round-Trip Requests and Elicitation

A tool or prompt can return `InputRequired` instead of completing immediately.
The client collects the requested input and retries the original request with a
new JSON-RPC ID. Each request is independent: another server process can handle
the retry. This implements the MCP 2026-07-28
[multi round-trip pattern](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)
and
[elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation).

`Arguments.continuation` provides the original method, name and arguments, plus
the current request's `input_responses` and `request_state`. It is `None` for
direct Python calls made without a transport context. Use `NoArguments` rather
than `type(None)` when a function needs this context but has no business inputs.
Prompt functions support the same `InvocationResult[tuple[PromptMessage, ...]]`
contract.

`context.elicitation_modes` is the immutable set of supported modes (`"form"`
and/or `"url"`), or an empty set. Applications can inspect it to choose an
alternative flow before requesting input; the transport also enforces it when
serializing the result.

## Requesting a form

This example assumes the application authenticates every request, provides a
shared `SignedStateCodec` as `request.state.continuation_signer`, and puts the
verified OAuth client ID in `request.state.oauth_client_id`. With `auth_mcp`,
`request.user.display_name` is the subject returned by the token validator.
Custom authentication backends must supply a stable, verified user identifier.
Neither client IDs from unverified request parameters nor MCP `clientInfo` are
authentication identities.

```python
from typing import assert_never

from pydantic import BaseModel, ConfigDict, Field

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
    InvocationResult,
    MissingInputResponse,
    NoArguments,
    SignedStateCodec,
    StringField,
    Tool,
    ValidatedInput,
    VerifiedState,
)


class Profile(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    nickname: str = Field(min_length=1, max_length=100)


def request_profile(state: str) -> InputRequired:
    return InputRequired(
        input_requests={
            "profile": ElicitationRequest(
                params=FormElicitation(
                    message="What should we call you?",
                    requested_schema=ElicitationSchema(
                        properties={
                            "nickname": StringField(min_length=1, max_length=100),
                        },
                        required=("nickname",),
                    ),
                ),
            ),
        },
        request_state=state,
    )


def profile(args: Arguments[NoArguments]) -> InvocationResult[Profile]:
    context = args.continuation
    if context is None:
        return InvalidContinuationState()
    signer = args.get_state_key("continuation_signer", SignedStateCodec)
    client_id = args.get_state_key("oauth_client_id", str)
    binding = context.bind(args.request.user.display_name, client_id=client_id)
    state = context.request_state
    if state is None:
        return request_profile(signer.seal({"step": "profile"}, binding))

    match signer.open(state, binding):
        case InvalidContinuationState() as failure:
            return failure
        case VerifiedState():
            pass
        case _ as unreachable:
            assert_never(unreachable)

    match context.form_content("profile", Profile):
        case ValidatedInput(value=value):
            return value
        case MissingInputResponse():
            return request_profile(state)
        case InvalidInputResponse() as invalid_input:
            return invalid_input
        case DeclinedElicitation() | CancelledElicitation():
            return Profile(nickname="Guest")
        case _ as unhandled_input:
            assert_never(unhandled_input)


profile_tool = Tool(
    func=profile,
    inputs=NoArguments,
    output=Profile,
    scopes=("profile",),
)
```

The form schema accepts strings, numbers, integers, booleans, single-choice
fields, and arrays of string choices. Use `ChoiceField`, `TitledChoiceField` and
`MultiChoiceField` for selections. Nested objects and arbitrary arrays are
rejected. `form_content` validates accepted content against your application
model; use matching constraints on that model and the published form schema. It
keeps decline, cancel, missing input and malformed input distinct. Unknown
response keys are ignored unless the application reads them. A missing required
response can be requested again, as above.

The client must advertise `elicitation` in each request's `_meta` capabilities.
`{"elicitation": {}}` supports form mode; explicit
`{"elicitation": {"form": {}, "url": {}}}` supports both modes. A missing
elicitation capability returns `-32021` with `requiredCapabilities` (HTTP 400).
A declared capability missing the requested mode returns `-32602`. Neither
failure sends unsupported input requests to the client. No server-level
elicitation capability is advertised: it is a client feature.

The initial result contains `resultType: "input_required"`, `inputRequests`,
optional `requestState`, and the usual server `_meta`. It has no complete tool
output or prompt messages. Successful retries retain the usual complete result.
Authorization scopes and mirrored HTTP headers are checked on every retry.

## Signed continuation state

Create `SignedStateCodec(secret, ttl_seconds=300)` once at application setup.
Use at least 32 cryptographically random secret bytes from secret management,
shared by all instances. Persist that secret across process restarts; changing
it invalidates outstanding tokens. Do not generate a different key per request.

`seal(payload, binding)` produces an HMAC-SHA256 token. `open(token, binding)`
returns either `VerifiedState(payload)` or `InvalidContinuationState`. The token
expires after its TTL and is bound to the authenticated user, verified client,
method, tool or prompt name, and original arguments. The JSON-RPC ID and retry
inputs are not part of that binding. Verification must happen before trusting
state or performing effects. Returning `InvalidContinuationState` or
`InvalidInputResponse` from a tool or prompt produces a sanitized `-32602`
error.

State is authenticated, **not encrypted**. It must not contain credentials or
other sensitive data. Tokens are limited to 64 KiB. A token can be replayed by
the same caller on the same operation until expiry; an action requiring at most
one execution must enforce that rule in application storage. Signing does not
replace authentication, current authorization checks, or idempotency handling.
The opaque `request_state` string is always untrusted until verified. Custom
state formats remain possible; the application must validate them and protect
their integrity whenever they influence behavior or access.

`RetryRequired(request_state=...)` provides a state-only continuation without an
input request or client-capability requirement. This is useful when the client
can retry without collecting user input. `InputRequired` requires a nonempty
request map; a response cannot accidentally contain neither requests nor state.

## URL elicitation

```python
from http_mcp.types import ElicitationRequest, InputRequired, UrlElicitation

result = InputRequired(
    input_requests={
        "connect": ElicitationRequest(
            params=UrlElicitation(
                message="Connect your account on our secure website",
                url="https://service.example.com/connect",
            ),
        ),
    },
)
```

URL mode requires explicit `{"elicitation": {"url": {}}}` support. URL strings
are validated and retain their exact spelling. Read the result through
`context.input_response("connect")`; it returns `AcceptedElicitation`,
`DeclinedElicitation`, `CancelledElicitation`, `MissingInputResponse` or
`InvalidInputResponse`. URL acceptance can omit form content. Confirm completion
through your own trusted backend rather than treating acceptance as proof that
an external operation succeeded.

Forms must not request passwords, API keys or other sensitive information. Use
an independently authenticated web flow for those interactions. Do not put user
data, credentials or preauthenticated access links in elicitation URLs, and
verify that the web user is the same user who initiated the request. URL mode
must not replace authorization to the MCP server itself. The library emits
protocol data; the client is responsible for consent and opening the URL.

## Scope of this increment

MRTR is supported for `tools/call` and `prompts/get`, over HTTP and STDIO.
Elicitation supports form and URL requests, including multiple named requests in
one result. This increment does not add resources, streaming subscriptions,
progress, cancellation, or optional extensions. Deprecated sampling and roots
requests are not added. Existing complete-result calls remain compatible; custom
`ServerInterface` implementations can return the new invocation outcomes without
changing method signatures. Direct invocation consumers must handle the new
`InvocationResult` variants.
