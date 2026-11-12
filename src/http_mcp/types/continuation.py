"""Stateless invocation context and integrity-protected continuation state.

State is authenticated, not encrypted. Do not place credentials or other secrets in it.
The application supplies a stable, verified principal; client metadata is not identity.
"""

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, StrictInt, StrictStr

from http_mcp._mcp_types.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    ElicitationMode,
    ElicitationResponse,
    InputRequired,
    RetryRequired,
)
from http_mcp._parsing import InvalidJson, InvalidModel, Parsed, parse_json, parse_model

INVOCATION_CONTEXT_KEY = "http_mcp.invocation_context"
_MAX_STATE_LENGTH = 65536


@dataclass(frozen=True)
class InvalidContinuationState:
    message: str = field(default="Invalid continuation input", init=False)
    type: Literal["invalid_continuation_state"] = "invalid_continuation_state"


@dataclass(frozen=True)
class VerifiedState:
    payload: JsonValue
    type: Literal["verified_state"] = "verified_state"


@dataclass(frozen=True)
class MissingInputResponse:
    key: str
    type: Literal["missing_input_response"] = "missing_input_response"


@dataclass(frozen=True)
class InvalidInputResponse:
    key: str
    message: str = field(default="Invalid continuation input", init=False)
    type: Literal["invalid_input_response"] = "invalid_input_response"


type InvocationResult[T] = (
    T | InputRequired | RetryRequired | InvalidContinuationState | InvalidInputResponse
)


@dataclass(frozen=True)
class ContinuationBinding:
    """Identity and salient original parameters to which a continuation belongs."""

    principal: str
    method: Literal["tools/call", "prompts/get", "resources/read"]
    name: str
    client_id: str
    arguments: dict[str, JsonValue] = field(default_factory=dict)

    def digest(self) -> str:
        serialized = json.dumps(
            [self.principal, self.client_id, self.method, self.name, self.arguments],
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode()).hexdigest()


class _StatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    binding: StrictStr = Field(pattern="^[0-9a-f]{64}$", max_length=64)
    expires_at: StrictInt
    payload: JsonValue


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode(data: str) -> bytes | InvalidContinuationState:
    """Adapt the base64 parser's exceptions to a domain failure."""
    try:
        decoded = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        return InvalidContinuationState()
    # Accept a single canonical spelling, including unused padding bits.
    if _encode(decoded) != data:
        return InvalidContinuationState()
    return decoded


@dataclass(frozen=True)
class SignedStateCodec:
    """HMAC-SHA256 state with expiry and mandatory caller/request binding.

    Use the same secret (at least 32 random bytes) on every serving instance.
    It must come from application secret management, never from a client.
    Tokens can be replayed within their TTL; single-use actions need application storage.
    """

    secret: bytes = field(repr=False)
    ttl_seconds: int = 300

    def __post_init__(self) -> None:
        """Reject invalid application signing configuration before serving requests."""
        if len(self.secret) < 32:  # noqa: PLR2004
            message = "Continuation signing requires at least 32 secret bytes"
            raise ValueError(message)
        if type(self.ttl_seconds) is not int or self.ttl_seconds <= 0:
            message = "Continuation TTL must be a positive integer"
            raise ValueError(message)

    def seal(self, payload: JsonValue, binding: ContinuationBinding) -> str:
        state = _StatePayload(
            binding=binding.digest(),
            expires_at=int(time.time()) + self.ttl_seconds,
            payload=payload,
        )
        body = "v1." + _encode(state.model_dump_json().encode())
        signature = hmac.digest(self.secret, body.encode("ascii"), "sha256")
        token = body + "." + _encode(signature)
        if len(token) > _MAX_STATE_LENGTH:
            message = "Continuation state exceeds 64 KiB"
            raise ValueError(message)
        return token

    def open(
        self,
        token: str,
        binding: ContinuationBinding,
    ) -> VerifiedState | InvalidContinuationState:
        if len(token) > _MAX_STATE_LENGTH or not token.isascii():
            return InvalidContinuationState()
        match token.split("."):
            case ["v1", encoded, signature]:
                body = "v1." + encoded
                expected = _encode(hmac.digest(self.secret, body.encode("ascii"), "sha256"))
                if not hmac.compare_digest(signature, expected):
                    return InvalidContinuationState()
                return self._verified_payload(encoded, binding)
            case _:
                return InvalidContinuationState()

    def _verified_payload(
        self,
        encoded: str,
        binding: ContinuationBinding,
    ) -> VerifiedState | InvalidContinuationState:
        match _decode(encoded):
            case InvalidContinuationState() as failure:
                return failure
            case bytes() as decoded:
                match parse_json(decoded):
                    case InvalidJson():
                        return InvalidContinuationState()
                    case Parsed(value=value):
                        return self._validate_payload(value, binding)
                    case _ as unreachable:
                        assert_never(unreachable)
            case _ as unreachable:
                assert_never(unreachable)

    def _validate_payload(
        self,
        value: object,
        binding: ContinuationBinding,
    ) -> VerifiedState | InvalidContinuationState:
        match parse_model(_StatePayload, value):
            case InvalidModel():
                return InvalidContinuationState()
            case Parsed(value=state):
                if state.expires_at <= time.time() or not hmac.compare_digest(
                    state.binding,
                    binding.digest(),
                ):
                    return InvalidContinuationState()
                return VerifiedState(state.payload)
            case _ as unreachable:
                assert_never(unreachable)


class _ElicitationResponse(RootModel[ElicitationResponse]):
    pass


@dataclass(frozen=True)
class InvocationContext:
    """Per-request MRTR inputs. A retry is independent of the initial request.

    Unknown response keys are ignored unless the application explicitly reads them.
    ``request_state`` is untrusted until checked with ``SignedStateCodec.open``.
    """

    method: Literal["tools/call", "prompts/get"]
    name: str
    arguments: dict[str, JsonValue]
    input_responses: dict[str, JsonValue] = field(default_factory=dict)
    request_state: str | None = None
    elicitation_modes: frozenset[ElicitationMode] = frozenset()

    def bind(self, principal: str, *, client_id: str) -> ContinuationBinding:
        """Bind to identities verified by the application, not client request metadata."""
        return ContinuationBinding(principal, self.method, self.name, client_id, self.arguments)

    def input_response(
        self,
        key: str,
    ) -> ElicitationResponse | MissingInputResponse | InvalidInputResponse:
        if key not in self.input_responses:
            return MissingInputResponse(key)
        match parse_model(_ElicitationResponse, self.input_responses[key]):
            case InvalidModel():
                return InvalidInputResponse(key)
            case Parsed(value=response):
                return response.root
            case _ as unreachable:
                assert_never(unreachable)

    def form_content[T: BaseModel](
        self,
        key: str,
        model: type[T],
    ) -> (
        Parsed[T]
        | MissingInputResponse
        | InvalidInputResponse
        | DeclinedElicitation
        | CancelledElicitation
    ):
        """Validate accepted form data with an application model, preserving refusal states."""
        match self.input_response(key):
            case AcceptedElicitation(content=content) if content is not None:
                match parse_model(model, content):
                    case Parsed() as validated:
                        return validated
                    case InvalidModel():
                        return InvalidInputResponse(key)
                    case _ as unreachable:
                        assert_never(unreachable)
            case AcceptedElicitation():
                return InvalidInputResponse(key)
            case (
                MissingInputResponse()
                | InvalidInputResponse()
                | DeclinedElicitation()
                | CancelledElicitation() as response
            ):
                return response
            case _ as unreachable:
                assert_never(unreachable)
