"""Streamable HTTP request-metadata headers (revision ``2026-07-28``).

The transport mirrors selected body fields into HTTP headers so intermediaries can
route and rate-limit without parsing the body. A server that reads the body must
verify the two agree, otherwise a load balancer and the server could act on
different values for the same request.
"""

import base64
import binascii
from collections.abc import Mapping
from typing import Any, Final

BASE64_PREFIX: Final = "=?base64?"
BASE64_SUFFIX: Final = "?="
HEADER_PARAM_PREFIX: Final = "mcp-param-"


class _Missing:
    """Sentinel distinguishing an absent argument from one explicitly set to null."""

    def __repr__(self) -> str:
        """Return a readable placeholder for debugging output."""
        return "<missing>"


MISSING: Final = _Missing()


def decode_header_value(value: str) -> str | None:
    """Unwrap the Base64 sentinel format, or return the value unchanged.

    Returns ``None`` when the sentinel is present but its payload is not valid
    Base64-encoded UTF-8, which the caller reports as a header mismatch.
    """
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
        return None


def is_valid_header_value(value: str) -> bool:
    """Report whether a raw header value is within the RFC 9110 field-value set."""
    return all(char == "\t" or "\x20" <= char <= "\x7e" for char in value)


def collect_header_params(schema: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """Map each ``x-mcp-header`` name to the property path it mirrors.

    Only properties statically reachable through a chain of ``properties`` keys are
    considered; the spec excludes annotations reached via ``items``, ``$ref``, or a
    composition or conditional keyword, so walking ``properties`` alone is the rule.
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
                found[header_name.lower()] = (*path, name)
            walk(subschema, (*path, name))

    walk(schema, ())
    return found


def extract_argument(arguments: Mapping[str, Any], path: tuple[str, ...]) -> Any:  # noqa: ANN401
    """Read the value at an exact property path, or ``MISSING`` if absent."""
    current: Any = arguments
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return MISSING
        current = current[key]
    return current


def values_match(header_value: str, body_value: object) -> bool:
    """Compare a decoded header value against the value carried in the body."""
    if isinstance(body_value, bool):
        return header_value == ("true" if body_value else "false")
    if isinstance(body_value, int | float):
        try:
            return float(header_value) == float(body_value)
        except ValueError:
            return False
    if isinstance(body_value, str):
        return header_value == body_value
    return False
