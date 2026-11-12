import base64
import hashlib
import hmac
from dataclasses import replace

import pytest
from pydantic import BaseModel, JsonValue

from http_mcp.types import (
    CancelledElicitation,
    ContinuationBinding,
    DeclinedElicitation,
    InvalidContinuationState,
    InvalidInputResponse,
    InvocationContext,
    MissingInputResponse,
    SignedStateCodec,
    ValidatedInput,
    VerifiedState,
)

SECRET = b"unit-test-only-signing-key-32-bytes"
BINDING = ContinuationBinding("user-123", "tools/call", "greet", "client-123", {"topic": "MCP"})


@pytest.mark.parametrize("payload", [None, True, 42, "text", ["a", 3], {"step": 1}])
def test_state_round_trip_across_independent_instances(payload: JsonValue) -> None:
    token = SignedStateCodec(SECRET).seal(payload, BINDING)
    assert SignedStateCodec(SECRET).open(token, BINDING) == VerifiedState(payload)
    assert "unit-test-only" not in repr(SignedStateCodec(SECRET))


@pytest.mark.parametrize(
    "binding",
    [
        replace(BINDING, principal="user-456"),
        replace(BINDING, client_id="client-456"),
        replace(BINDING, method="prompts/get"),
        replace(BINDING, name="other_tool"),
        replace(BINDING, arguments={"topic": "other"}),
    ],
)
def test_state_is_bound_to_principal_method_name_and_arguments(
    binding: ContinuationBinding,
) -> None:
    codec = SignedStateCodec(SECRET)
    assert codec.open(codec.seal({"step": 1}, BINDING), binding) == InvalidContinuationState()


def test_json_key_order_does_not_change_binding() -> None:
    codec = SignedStateCodec(SECRET)
    binding = replace(BINDING, arguments={"a": 1, "b": "2"})
    reordered = replace(binding, arguments={"b": "2", "a": 1})
    assert codec.open(codec.seal(None, binding), reordered) == VerifiedState(None)
    assert (
        codec.open(codec.seal(None, binding), replace(binding, arguments={"a": True, "b": "2"}))
        == InvalidContinuationState()
    )


@pytest.mark.parametrize("token", ["", "v1", "v1.a.b.c", "v2.a.b", "v1.é.a", "x" * 65537])
def test_malformed_state_is_a_value(token: str) -> None:
    assert SignedStateCodec(SECRET).open(token, BINDING) == InvalidContinuationState()


def test_signature_and_signing_key_are_verified() -> None:
    codec = SignedStateCodec(SECRET)
    token = codec.seal({"step": 1}, BINDING)
    assert codec.open(token + "x", BINDING) == InvalidContinuationState()
    assert (
        SignedStateCodec(b"a-different-unit-test-key-32-bytes").open(token, BINDING)
        == InvalidContinuationState()
    )
    version, body, signature = token.split(".")
    assert codec.open(f"{version}.A{body[1:]}.{signature}", BINDING) == InvalidContinuationState()


def test_expiry_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("http_mcp.types.continuation.time.time", lambda: 1000.0)
    codec = SignedStateCodec(SECRET, ttl_seconds=10)
    token = codec.seal({"step": 1}, BINDING)
    monkeypatch.setattr("http_mcp.types.continuation.time.time", lambda: 1009.99)
    assert codec.open(token, BINDING) == VerifiedState({"step": 1})
    monkeypatch.setattr("http_mcp.types.continuation.time.time", lambda: 1010.0)
    assert codec.open(token, BINDING) == InvalidContinuationState()


@pytest.mark.parametrize(
    "encoded",
    [
        "!",
        "A",
        "====",
        base64.urlsafe_b64encode(b"not json").decode().rstrip("="),
        base64.urlsafe_b64encode(b"{}").decode().rstrip("="),
    ],
)
def test_authentic_but_malformed_payload_is_rejected(encoded: str) -> None:
    # Exercise parser boundaries after a valid signature, e.g. a future or broken issuer.
    body = f"v1.{encoded}"
    signature = (
        base64.urlsafe_b64encode(hmac.digest(SECRET, body.encode(), hashlib.sha256))
        .decode()
        .rstrip("=")
    )
    assert (
        SignedStateCodec(SECRET).open(body + "." + signature, BINDING) == InvalidContinuationState()
    )


@pytest.mark.parametrize("secret", [b"", b"a" * 31])
def test_short_signing_keys_are_configuration_errors(secret: bytes) -> None:
    with pytest.raises(ValueError, match="32 secret bytes"):
        SignedStateCodec(secret)


@pytest.mark.parametrize("ttl", [0, -1, True])
def test_invalid_ttl_is_a_configuration_error(ttl: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        SignedStateCodec(SECRET, ttl_seconds=ttl)


def test_oversized_generated_state_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="64 KiB"):
        SignedStateCodec(SECRET).seal("x" * 65536, BINDING)


class FormData(BaseModel):
    name: str


@pytest.mark.parametrize(
    ("action", "response_type"),
    [("decline", DeclinedElicitation), ("cancel", CancelledElicitation)],
)
def test_form_content_preserves_user_refusal(action: str, response_type: type) -> None:
    context = InvocationContext("tools/call", "greet", {}, {"form": {"action": action}})
    assert isinstance(context.form_content("form", FormData), response_type)


def test_form_content_validates_only_the_selected_key() -> None:
    context = InvocationContext(
        "tools/call",
        "greet",
        {},
        {"form": {"action": "accept", "content": {"name": "Ada"}}, "unknown": [1, 2, 3]},
    )
    assert context.form_content("form", FormData) == ValidatedInput(FormData(name="Ada"))
    assert context.form_content("missing", FormData) == MissingInputResponse("missing")
    assert context.form_content("unknown", FormData) == InvalidInputResponse("unknown")
