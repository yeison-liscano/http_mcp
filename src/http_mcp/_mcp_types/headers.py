"""Streamable HTTP request-metadata headers (revision ``2026-07-28``).

The transport mirrors selected body fields into HTTP headers so intermediaries can
route and rate-limit without parsing the body. A server that reads the body must
verify the two agree, otherwise a load balancer and the server could act on
different values for the same request.
"""

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, assert_never

BASE64_PREFIX: Final = "=?base64?"
BASE64_SUFFIX: Final = "?="
HEADER_PARAM_PREFIX: Final = "mcp-param-"

type JsonValue = str | int | float | bool | list[Any] | dict[str, Any] | None


@dataclass(frozen=True)
class MalformedHeaderValue:
    """The Base64 sentinel is present but its payload is not valid Base64-encoded UTF-8."""

    type: Literal["malformed_header_value"] = "malformed_header_value"


@dataclass(frozen=True)
class ArgumentAbsent:
    """The property path does not exist in the tool arguments."""

    type: Literal["argument_absent"] = "argument_absent"


@dataclass(frozen=True)
class ArgumentPresent:
    """The property path exists. Its value may still be an explicit null."""

    value: JsonValue
    type: Literal["argument_present"] = "argument_present"


def decode_header_value(value: str) -> str | MalformedHeaderValue:
    """Unwrap the Base64 sentinel format, or return the value unchanged."""
    if not (
        len(value) >= len(BASE64_PREFIX) + len(BASE64_SUFFIX)
        and value.startswith(BASE64_PREFIX)
        and value.endswith(BASE64_SUFFIX)
    ):
        return value
    payload = value[len(BASE64_PREFIX) : -len(BASE64_SUFFIX)]
    try:
        return base64.b64decode(payload, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return MalformedHeaderValue()


def is_valid_header_value(value: str) -> bool:
    """Report whether a raw header value is within the RFC 9110 field-value set."""
    return all(char == "\t" or "\x20" <= char <= "\x7e" for char in value)


class DuplicateHeaderParamError(ValueError):
    """Raised when two properties claim the same ``x-mcp-header`` name.

    Header names are matched case-insensitively, so ``tenant`` and ``Tenant`` collide.
    Silently keeping one of the two would leave the other property unvalidated while
    the server still believed it was checking it, so this fails closed instead.
    """

    def __init__(self, header_name: str, first: tuple[str, ...], second: tuple[str, ...]) -> None:
        self.header_name = header_name
        super().__init__(
            f"Duplicate x-mcp-header {header_name!r} declared by both "
            f"{'.'.join(first)!r} and {'.'.join(second)!r}",
        )


def collect_header_params(schema: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """Map each ``x-mcp-header`` name to the property path it mirrors.

    Only properties statically reachable through a chain of ``properties`` keys are
    considered; the spec excludes annotations reached via ``items``, ``$ref``, or a
    composition or conditional keyword, so walking ``properties`` alone is the rule.

    Raises :class:`DuplicateHeaderParamError` when two properties claim the same
    header name. A tool whose schema collides this way cannot be validated correctly,
    so it must not be served at all.
    """
    found: dict[str, tuple[str, ...]] = {}

    def walk(node: Mapping[str, Any], path: tuple[str, ...]) -> None:
        properties = node.get("properties")
        if not isinstance(properties, dict):
            return
        for name, subschema in properties.items():
            if not isinstance(subschema, dict):
                continue
            header_name = subschema.get("x-mcp-header")
            if isinstance(header_name, str) and header_name:
                key = header_name.lower()
                if key in found:
                    raise DuplicateHeaderParamError(key, found[key], (*path, name))
                found[key] = (*path, name)
            walk(subschema, (*path, name))

    walk(schema, ())
    return found


def extract_argument(
    arguments: Mapping[str, JsonValue],
    path: tuple[str, ...],
) -> ArgumentAbsent | ArgumentPresent:
    """Read the value at an exact property path."""
    current: Any = arguments
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return ArgumentAbsent()
        current = current[key]
    return ArgumentPresent(current)


def _render_number(value: float) -> str | None:
    """Return the JSON spelling, or None when the number has no JSON representation."""
    try:
        return json.dumps(value, allow_nan=False)
    except ValueError:
        return None


def values_match(header_value: str, body_value: JsonValue) -> bool:
    """Compare a decoded header value against the value carried in the body.

    The comparison is textual, against the value as JSON writes it. Coercing both
    sides with ``float()`` would accept spellings that only Python reads as equal —
    ``"1_0"``, ``" 10 "``, ``"1e1"``, ``"+10"`` all parse to ``10`` — while an
    intermediary routing or rate-limiting on the raw header sees a different value
    than the server acts on. Byte agreement is the property that mirroring exists to
    guarantee, so byte agreement is what gets checked.
    """
    match body_value:
        case bool():
            return header_value == ("true" if body_value else "false")
        case int() | float():
            return header_value == _render_number(body_value)
        case str():
            return header_value == body_value
        case None | list() | dict():
            return False
        case _ as unreachable:
            assert_never(unreachable)
