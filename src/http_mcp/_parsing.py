"""Adapters that turn the exceptions of parsing libraries into values.

`json.loads` and pydantic report invalid input only by raising. Invalid input is an
expected failure, so these functions are the one place those exceptions are caught and
everything else matches on the outcome.
"""

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class Parsed[T]:
    value: T
    type: Literal["parsed"] = "parsed"


@dataclass(frozen=True)
class InvalidJson:
    type: Literal["invalid_json"] = "invalid_json"


@dataclass(frozen=True)
class InvalidModel:
    """Input rejected by a model. `description` is sanitized and safe to send to clients."""

    description: str
    type: Literal["invalid_model"] = "invalid_model"


def sanitize_validation_errors(error: ValidationError) -> str:
    """Return a sanitized JSON string from a Pydantic ValidationError.

    Keeps only field locations and human-readable messages, stripping
    internal details (raw input, Pydantic URLs, error type codes).

    """
    sanitized = tuple(
        {"field": ".".join(str(loc) for loc in err["loc"]), "message": err["msg"]}
        for err in error.errors()
    )
    return json.dumps(sanitized)


def parse_json(data: bytes) -> Parsed[object] | InvalidJson:
    """Decode a JSON document.

    `ValueError` covers malformed JSON, bodies that are not valid UTF-8, and integers past
    the interpreter's digit limit. `RecursionError` covers pathologically nested documents.
    """
    try:
        return Parsed(json.loads(data))
    except (ValueError, RecursionError):
        return InvalidJson()


def parse_model[T: BaseModel](model: type[T], data: object) -> Parsed[T] | InvalidModel:
    try:
        return Parsed(model.model_validate(data))
    except ValidationError as e:
        return InvalidModel(sanitize_validation_errors(e))
